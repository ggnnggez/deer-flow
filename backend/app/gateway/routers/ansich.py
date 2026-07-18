import base64
import binascii
import hashlib
import json
import logging
from datetime import datetime
from typing import Literal

from ansich.contracts import ControlValue, TaskLifecycleScope
from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.gateway.deps import require_admin_user

router = APIRouter(prefix="/api/ansich", tags=["ansich"])
_ADMIN_REQUIRED = "Ansich developer/operator observability requires an admin account."
logger = logging.getLogger(__name__)


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


def _decode_compression_cursor(
    value: str | None,
) -> tuple[datetime, str] | None:
    if value is None:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(decoded, list) or len(decoded) != 2 or not all(isinstance(item, str) for item in decoded):
            raise ValueError
        occurred_at = datetime.fromisoformat(decoded[0])
        if occurred_at.tzinfo is None:
            raise ValueError
        return occurred_at, decoded[1]
    except (
        binascii.Error,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid Ansich ContextCompression cursor",
        ) from exc


def _encode_timeline_cursor(occurred_at: datetime, ingest_seq: int) -> str:
    payload = json.dumps([occurred_at.isoformat(), ingest_seq], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_timeline_cursor(value: str | None) -> tuple[datetime, int] | None:
    if value is None:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(decoded, list) or len(decoded) != 2 or not isinstance(decoded[0], str) or not isinstance(decoded[1], int) or decoded[1] < 1:
            raise ValueError
        occurred_at = datetime.fromisoformat(decoded[0])
        if occurred_at.tzinfo is None:
            raise ValueError
        return occurred_at, decoded[1]
    except (binascii.Error, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid Ansich timeline cursor") from exc


@router.get("/operations/active-tasks", response_model=None)
async def list_active_tasks(
    request: Request,
    response: Response,
    owner: str | None = Query(default=None),
    agent: str | None = Query(default=None),
    control: ControlValue | None = Query(default=None),
    heartbeat: Literal["unknown", "fresh", "stale"] | None = Query(default=None),
    budget: Literal["unknown", "within", "warning", "exceeded"] | None = Query(default=None),
    min_duration_ms: int | None = Query(default=None, ge=0),
    max_duration_ms: int | None = Query(default=None, ge=0),
    observability: Literal["healthy", "degraded"] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None),
) -> dict | Response:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    decoded_cursor = _decode_cursor(cursor)
    query = {
        "limit": limit + 1,
        "owner_id": owner,
        "agent_id": agent,
        "control": control,
        "heartbeat_status": heartbeat,
        "budget_status": budget,
        "min_duration_ms": min_duration_ms,
        "max_duration_ms": max_duration_ms,
        "observability_status": observability,
        "cursor": decoded_cursor,
    }
    try:
        tasks = await service.list_active_tasks(**query)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich active Task query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    page = tasks[:limit]
    next_cursor = None
    if len(tasks) > limit and page:
        next_cursor = _encode_cursor(
            page[-1].last_evidence_at,
            page[-1].task_id,
        )
    body = {
        "items": [task.model_dump(mode="json") for task in page],
        "next_cursor": next_cursor,
        "projection_status": _projection_status(service),
        "updated_at": max(
            (task.updated_at for task in page),
            default=None,
        ),
    }
    etag_payload = json.dumps(
        {
            "items": body["items"],
            "next_cursor": body["next_cursor"],
        },
        sort_keys=True,
        default=str,
    ).encode()
    etag = f'"{hashlib.sha256(etag_payload).hexdigest()}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    return body


@router.get("/tasks/{task_id}/usage")
async def get_task_usage(task_id: str, request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        task = await service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Ansich Task not found")
        usage = await service.get_task_usage(task_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich Usage query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    return {
        "usage": usage.model_dump(mode="json"),
        "projection_status": _projection_status(service),
    }


@router.get("/tasks/{task_id}/budgets")
async def get_task_budgets(task_id: str, request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        task = await service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Ansich Task not found")
        budgets = await service.get_task_budgets(task_id)
        health = await service.get_task_budget_health(task_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich Budget query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    return {
        "budgets": budgets.model_dump(mode="json"),
        "health": [item.model_dump(mode="json") for item in health],
        "projection_status": _projection_status(service),
    }


@router.get("/tasks")
async def list_tasks(
    request: Request,
    control: ControlValue | None = Query(default=None),
    lifecycle_scope: TaskLifecycleScope = Query(default="all"),
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
            lifecycle_scope=lifecycle_scope,
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
async def get_task_timeline(
    task_id: str,
    request: Request,
    limit: int = Query(default=200, ge=1, le=500),
    cursor: str | None = Query(default=None),
) -> dict:
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
        observations = await service.list_timeline(
            task_id,
            limit=limit + 1,
            cursor=_decode_timeline_cursor(cursor),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"message": "Ansich timeline query failed", "projection_status": _projection_status(service)},
        ) from exc
    page = observations[:limit]
    next_cursor = None
    if len(observations) > limit and page:
        last_seq, last_observation = page[-1]
        next_cursor = _encode_timeline_cursor(last_observation.occurred_at, last_seq)
    return {
        "items": [_timeline_item(ingest_seq, observation) for ingest_seq, observation in page],
        "next_cursor": next_cursor,
        "projection_status": _projection_status(service),
    }


def _timeline_item(ingest_seq: int, observation) -> dict:
    item = {"ingest_seq": ingest_seq, **observation.model_dump(mode="json")}
    payload = item.get("payload")
    # Raw ContentBlock bodies leave only through the logged raw-payload
    # endpoint; the polling timeline carries inventory metadata only.
    if observation.kind == "content.produced" and isinstance(payload, dict):
        item["payload"] = {key: value for key, value in payload.items() if key != "body"}
    return item


@router.get("/tasks/{task_id}/steps")
async def list_task_steps(task_id: str, request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        task = await service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Ansich Task not found")
        steps = await service.list_steps(task_id)
        system_operations = await service.list_system_operations(task_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"message": "Ansich Step query failed", "projection_status": _projection_status(service)},
        ) from exc
    return {
        "items": [step.model_dump(mode="json") for step in steps],
        "system_operations": [operation.model_dump(mode="json") for operation in system_operations],
        "projection_status": _projection_status(service),
    }


@router.get("/steps/{step_id}")
async def get_step(step_id: str, request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        step = await service.get_step(step_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"message": "Ansich Step query failed", "projection_status": _projection_status(service)},
        ) from exc
    if step is None:
        raise HTTPException(status_code=404, detail="Ansich Step not found")
    return {"step": step.model_dump(mode="json"), "projection_status": _projection_status(service)}


@router.get("/steps/{step_id}/context")
async def get_step_context(step_id: str, request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        step = await service.get_step(step_id)
        if step is None:
            raise HTTPException(status_code=404, detail="Ansich Step not found")
        context = await service.get_step_context(step_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"message": "Ansich Context query failed", "projection_status": _projection_status(service)},
        ) from exc
    if context is None:
        raise HTTPException(status_code=404, detail="Ansich effective ContextSnapshot not found")
    return {"context": context.model_dump(mode="json"), "projection_status": _projection_status(service)}


@router.get("/context-snapshots/{snapshot_id}")
async def get_context_snapshot(snapshot_id: str, request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        context = await service.get_context_snapshot(snapshot_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich ContextSnapshot query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    if context is None:
        raise HTTPException(
            status_code=404,
            detail="Ansich ContextSnapshot not found",
        )
    return {
        "context": context.model_dump(mode="json"),
        "projection_status": _projection_status(service),
    }


async def _tool_call_or_404(service, tool_call_id: str):
    try:
        tool_call = await service.get_tool_call(tool_call_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich ToolCall query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    if tool_call is None:
        raise HTTPException(status_code=404, detail="Ansich ToolCall not found")
    return tool_call


@router.get("/tool-calls/{tool_call_id}")
async def get_tool_call(tool_call_id: str, request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    tool_call = await _tool_call_or_404(service, tool_call_id)
    return {
        "tool_call": tool_call.model_dump(mode="json"),
        "projection_status": _projection_status(service),
    }


async def _get_tool_result_payload(
    *,
    tool_call_id: str,
    role: str,
    request: Request,
    response: Response,
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    tool_call = await _tool_call_or_404(service, tool_call_id)
    results = tool_call.raw_results if role == "raw" else tool_call.visible_results
    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"Ansich ToolCall {role} result not found",
        )
    result = results[-1]
    try:
        payload = await service.get_content_block_payload(result.content_block_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": f"Ansich {role} tool result query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"Ansich ToolCall {role} payload not found",
        )
    user = getattr(request.state, "user", None)
    logger.info(
        "Ansich %s tool result accessed",
        role,
        extra={
            "ansich_tool_call_id": tool_call_id,
            "ansich_block_id": result.content_block_id,
            "ansich_result_role": role,
            "ansich_actor_id": str(getattr(user, "id", "unknown")),
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        f"{role}_result": result.model_dump(mode="json"),
        f"{role}_payload": payload.model_dump(mode="json"),
    }


@router.get("/tool-calls/{tool_call_id}/raw-result")
async def get_tool_raw_result(
    tool_call_id: str,
    request: Request,
    response: Response,
) -> dict:
    return await _get_tool_result_payload(
        tool_call_id=tool_call_id,
        role="raw",
        request=request,
        response=response,
    )


@router.get("/tool-calls/{tool_call_id}/visible-result")
async def get_tool_visible_result(
    tool_call_id: str,
    request: Request,
    response: Response,
) -> dict:
    return await _get_tool_result_payload(
        tool_call_id=tool_call_id,
        role="visible",
        request=request,
        response=response,
    )


@router.get("/content-blocks/{block_id}/payload")
async def get_content_block_payload(block_id: str, request: Request, response: Response) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        payload = await service.get_content_block_payload(block_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"message": "Ansich raw payload query failed", "projection_status": _projection_status(service)},
        ) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="Ansich ContentBlock payload not found")
    user = getattr(request.state, "user", None)
    logger.info(
        "Ansich raw content payload accessed",
        extra={
            "ansich_block_id": block_id,
            "ansich_actor_id": str(getattr(user, "id", "unknown")),
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return {"payload": payload.model_dump(mode="json")}


@router.get("/content-blocks/{block_id}/lineage")
async def get_content_block_lineage(
    block_id: str,
    request: Request,
    direction: Literal["backward", "forward"] = Query(default="backward"),
    depth: int = Query(default=8, ge=0, le=32),
    nodes: int = Query(default=500, ge=1, le=2_000),
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        lineage = await service.get_content_lineage(
            block_id,
            direction=direction,
            max_depth=depth,
            max_nodes=nodes,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich content lineage query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    if lineage is None:
        raise HTTPException(status_code=404, detail="Ansich ContentBlock not found")
    return {
        "lineage": lineage.model_dump(mode="json"),
        "projection_status": _projection_status(service),
    }


@router.get("/content-blocks/{block_id}/exposures")
async def get_content_block_exposures(
    block_id: str,
    request: Request,
    depth: int = Query(default=8, ge=0, le=32),
    nodes: int = Query(default=500, ge=1, le=2_000),
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        exposures = await service.get_possible_exposures(
            block_id,
            max_depth=depth,
            max_nodes=nodes,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich possible exposure query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    if exposures is None:
        raise HTTPException(status_code=404, detail="Ansich ContentBlock not found")
    return {
        "exposures": exposures.model_dump(mode="json"),
        "projection_status": _projection_status(service),
    }


@router.get("/context-compressions/{compression_id}")
async def get_context_compression(compression_id: str, request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        compression = await service.get_context_compression(compression_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich context compression query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    if compression is None:
        raise HTTPException(
            status_code=404,
            detail="Ansich ContextCompression not found",
        )
    return {
        "compression": compression.model_dump(mode="json"),
        "projection_status": _projection_status(service),
    }


@router.get("/tasks/{task_id}/context-compressions")
async def list_context_compressions(
    task_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None),
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    decoded_cursor = _decode_compression_cursor(cursor)
    try:
        task = await service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Ansich Task not found")
        compressions = await service.list_context_compressions(
            task_id,
            limit=limit + 1,
            cursor=decoded_cursor,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich ContextCompression list query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    page = compressions[:limit]
    next_cursor = None
    if len(compressions) > limit and page:
        next_cursor = _encode_cursor(
            page[-1].occurred_at,
            page[-1].source_obs_id,
        )
    return {
        "items": [item.model_dump(mode="json") for item in page],
        "next_cursor": next_cursor,
        "projection_status": _projection_status(service),
    }


@router.get("/health")
async def get_health(request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    return service.get_health().model_dump(mode="json")
