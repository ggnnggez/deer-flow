import asyncio
import base64
import binascii
import hashlib
import json
import logging
import posixpath
from datetime import datetime
from typing import Literal

from ansich.alerts import AlertWorkflowConflict
from ansich.contracts import ControlValue, TaskLifecycleScope
from ansich.credentials import contains_credential_like_material
from ansich.release import (
    AgentRelease,
    AgentReleaseFingerprint,
    compare_agent_releases,
)
from ansich.task_tree import TaskTreeDirection
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.gateway.deps import (
    get_current_user_from_request,
    get_run_manager,
    require_admin_user,
)
from deerflow.runtime.runs.manager import CancelOutcome
from deerflow.runtime.runs.schemas import RunStatus

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


def _decode_alert_cursor(
    value: str | None,
) -> tuple[datetime, str] | None:
    if value is None:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(decoded, list) or len(decoded) != 2 or not all(isinstance(item, str) for item in decoded):
            raise ValueError
        updated_at = datetime.fromisoformat(decoded[0])
        if updated_at.tzinfo is None:
            raise ValueError
        return updated_at, decoded[1]
    except (
        binascii.Error,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid Ansich Alert cursor",
        ) from exc


class AlertWorkflowRequest(BaseModel):
    workflow_version: int = Field(ge=1)


class AlertDismissRequest(AlertWorkflowRequest):
    reason: str = Field(min_length=1, max_length=512)


def _redact_release_prompt(manifest: dict) -> None:
    rendered_prompt = manifest["prompt"].pop("rendered_base_prompt", "")
    suffix = "…" if len(rendered_prompt) > 240 else ""
    manifest["prompt"]["rendered_base_prompt_preview"] = f"{rendered_prompt[:240]}{suffix}"


def _safe_release_detail(detail) -> dict:
    manifest = detail.manifest.model_dump(mode="json")
    _redact_release_prompt(manifest)
    return {
        "summary": detail.summary.model_dump(mode="json"),
        "manifest": manifest,
    }


def _release_from_detail(detail) -> AgentRelease:
    summary = detail.summary
    return AgentRelease(
        manifest=detail.manifest,
        fingerprint=AgentReleaseFingerprint(
            model_hash=summary.model_hash,
            prompt_hash=summary.prompt_hash,
            tool_catalog_hash=summary.tool_catalog_hash,
            policy_hash=summary.policy_hash,
            runtime_build_id=summary.runtime_build_id,
            release_hash=summary.release_hash,
        ),
    )


@router.get("/agent-releases")
async def list_agent_releases(
    request: Request,
    agent_name: str | None = Query(default=None, alias="agent"),
    component_hash: str | None = Query(default=None, alias="component"),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    for timestamp in (from_time, to_time):
        if timestamp is not None and timestamp.tzinfo is None:
            raise HTTPException(
                status_code=422,
                detail="Ansich AgentRelease time filters must include a timezone",
            )
    try:
        releases = await service.list_agent_releases(
            limit=limit,
            agent_name=agent_name,
            component_hash=component_hash,
            from_time=from_time,
            to_time=to_time,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich AgentRelease query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    return {
        "items": [item.model_dump(mode="json") for item in releases],
        "operational_distributions": {"availability": "unavailable"},
        "projection_status": _projection_status(service),
    }


@router.get("/agent-releases/compare")
async def compare_releases(
    request: Request,
    left: str = Query(min_length=1),
    right: str = Query(min_length=1),
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        left_detail = await service.get_agent_release(left)
        right_detail = await service.get_agent_release(right)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich AgentRelease comparison query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    if left_detail is None or right_detail is None:
        raise HTTPException(status_code=404, detail="Ansich AgentRelease not found")
    comparison = compare_agent_releases(
        _release_from_detail(left_detail),
        _release_from_detail(right_detail),
    )
    return {
        "comparison": comparison.model_dump(mode="json"),
        "projection_status": _projection_status(service),
    }


@router.get("/agent-releases/{release_id}")
async def get_agent_release(release_id: str, request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        detail = await service.get_agent_release(release_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich AgentRelease query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="Ansich AgentRelease not found")
    return {
        "release": _safe_release_detail(detail),
        "projection_status": _projection_status(service),
    }


@router.get("/agent-releases/{release_id}/manifest")
async def get_agent_release_manifest(
    release_id: str,
    request: Request,
    response: Response,
) -> dict:
    """Return the complete sanitized manifest through an audited, non-cached path."""

    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        detail = await service.get_agent_release(release_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich AgentRelease manifest query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="Ansich AgentRelease not found")
    user = getattr(request.state, "user", None)
    logger.info(
        "Ansich raw AgentRelease manifest accessed",
        extra={
            "ansich_release_id": release_id,
            "ansich_actor_id": str(getattr(user, "id", "unknown")),
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "release_id": release_id,
        "manifest": detail.manifest.model_dump(mode="json"),
    }


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


@router.get("/operations/alerts")
async def list_alerts(
    request: Request,
    alert_type: Literal[
        "budget_warning",
        "budget_exceeded",
        "exact_repetition",
        "tool_frequency",
        "heartbeat_missing",
        "long_dwell",
        "configuration_drift",
        "attempted_scope_violation",
        "realized_scope_violation",
        "unverified_effect",
    ]
    | None = Query(default=None, alias="type"),
    workflow_state: Literal[
        "open",
        "acknowledged",
        "dismissed",
        "resolved",
    ]
    | None = Query(default=None, alias="state"),
    task_id: str | None = Query(default=None, alias="task"),
    severity: Literal["info", "warning", "critical"] | None = Query(default=None),
    shadow: bool | None = Query(default=None),
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
            raise HTTPException(
                status_code=422,
                detail="Ansich Alert time filters must include a timezone",
            )
    try:
        alerts = await service.list_alerts(
            limit=limit + 1,
            alert_type=alert_type,
            workflow_state=workflow_state,
            task_id=task_id,
            severity=severity,
            shadow=shadow,
            from_time=from_time,
            to_time=to_time,
            cursor=_decode_alert_cursor(cursor),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich Alert query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    page = alerts[:limit]
    next_cursor = None
    if len(alerts) > limit and page:
        next_cursor = _encode_cursor(
            page[-1].updated_at,
            page[-1].alert_id,
        )
    return {
        "items": [item.model_dump(mode="json") for item in page],
        "next_cursor": next_cursor,
        "projection_status": _projection_status(service),
    }


@router.get("/operations/alerts/{alert_id}")
async def get_alert_detail(alert_id: str, request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        detail = await service.get_alert_detail(alert_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich Alert detail query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="Ansich Alert not found")
    return {
        "alert": detail.model_dump(mode="json"),
        "projection_status": _projection_status(service),
    }


async def _change_alert_workflow(
    *,
    alert_id: str,
    action: Literal["acknowledge", "dismiss"],
    workflow_version: int,
    reason: str | None,
    request: Request,
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    user = getattr(request.state, "user", None)
    if user is None:
        user = await get_current_user_from_request(request)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        if action == "acknowledge":
            alert = await service.acknowledge_alert(
                alert_id,
                expected_workflow_version=workflow_version,
                operator_id=str(user.id),
            )
        else:
            alert = await service.dismiss_alert(
                alert_id,
                expected_workflow_version=workflow_version,
                operator_id=str(user.id),
                reason=reason or "",
            )
    except AlertWorkflowConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Ansich Alert workflow version conflict",
                "current_alert": exc.current.model_dump(mode="json"),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich Alert workflow write failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    if alert is None:
        raise HTTPException(status_code=404, detail="Ansich Alert not found")
    return {
        "alert": alert.model_dump(mode="json"),
        "projection_status": _projection_status(service),
    }


@router.post("/operations/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    body: AlertWorkflowRequest,
    request: Request,
) -> dict:
    return await _change_alert_workflow(
        alert_id=alert_id,
        action="acknowledge",
        workflow_version=body.workflow_version,
        reason=None,
        request=request,
    )


@router.post("/operations/alerts/{alert_id}/dismiss")
async def dismiss_alert(
    alert_id: str,
    body: AlertDismissRequest,
    request: Request,
) -> dict:
    return await _change_alert_workflow(
        alert_id=alert_id,
        action="dismiss",
        workflow_version=body.workflow_version,
        reason=body.reason,
        request=request,
    )


async def _run_operator_action(
    *,
    task_id: str,
    action_type: Literal["interrupt", "rollback"],
    idempotency_key: str,
    request: Request,
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    if not idempotency_key.strip() or len(idempotency_key) > 128:
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key must contain 1 to 128 characters",
        )
    service = _service_or_503(request)
    _ensure_queryable(service)
    user = getattr(request.state, "user", None)
    if user is None:
        user = await get_current_user_from_request(request)
    operator_id = str(user.id)
    target = await service.get_task_action_target(task_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Ansich Task not found")
    if target.source_kind != "deerflow_run":
        raise HTTPException(
            status_code=409,
            detail="Ansich Task is not backed by a DeerFlow Run",
        )
    run_manager = get_run_manager(request)
    record = await run_manager.get(target.run_id)
    if record is None or record.run_id != target.run_id or (target.thread_id is not None and record.thread_id != target.thread_id):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Ansich Task source does not match the DeerFlow Run",
                "task_id": task_id,
                "run_id": target.run_id,
                "thread_id": target.thread_id,
            },
        )

    existing = await service.get_operator_action(
        task_id=task_id,
        action_type=action_type,
        idempotency_key=idempotency_key,
    )
    if existing is not None and existing.status in {"succeeded", "failed"}:
        return {
            "action": existing.model_dump(mode="json"),
            "audit_status": "recorded",
            "idempotent_replay": True,
        }
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Operator action is already in progress",
                "action": existing.model_dump(mode="json"),
            },
        )
    if target.control_value != "running" or record.status not in {RunStatus.pending, RunStatus.running}:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "DeerFlow Run does not support this action in its current state",
                "task_control": target.control_value,
                "run_status": str(record.status),
            },
        )

    audit_status = "recorded"
    action = None
    try:
        action, created = await service.begin_operator_action(
            task_id=task_id,
            action_type=action_type,
            idempotency_key=idempotency_key,
            operator_id=operator_id,
        )
        if not created:
            if action.status in {"succeeded", "failed"}:
                return {
                    "action": action.model_dump(mode="json"),
                    "audit_status": "recorded",
                    "idempotent_replay": True,
                }
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Operator action is already in progress",
                    "action": action.model_dump(mode="json"),
                },
            )
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Ansich operator action requested audit failed",
            extra={"ansich_task_id": task_id, "action_type": action_type},
        )
        audit_status = "degraded"

    runtime_error = None
    try:
        outcome = await run_manager.cancel(
            target.run_id,
            action=action_type,
        )
        succeeded = outcome in {
            CancelOutcome.cancelled,
            CancelOutcome.taken_over,
        }
        result: dict[str, object] = {"outcome": str(outcome)}
        if not succeeded:
            runtime_error = f"Run action was rejected: {outcome}"
    except Exception as exc:
        succeeded = False
        runtime_error = str(exc) or type(exc).__name__
        result = {
            "outcome": "exception",
            "error_type": type(exc).__name__,
            "message": runtime_error,
        }

    if action is not None:
        try:
            finished = await service.finish_operator_action(
                action.action_id,
                succeeded=succeeded,
                operator_id=operator_id,
                result=result,
            )
            if finished is not None:
                action = finished
            else:
                audit_status = "degraded"
        except Exception:
            logger.exception(
                "Ansich operator action terminal audit failed",
                extra={
                    "ansich_task_id": task_id,
                    "action_type": action_type,
                },
            )
            audit_status = "degraded"

    action_payload = (
        {
            "task_id": task_id,
            "action_type": action_type,
            "idempotency_key": idempotency_key,
            "status": "succeeded" if succeeded else "failed",
            "result": result,
        }
        if action is None
        else action.model_dump(mode="json")
    )
    body = {
        "action": action_payload,
        "audit_status": audit_status,
        "idempotent_replay": False,
    }
    if not succeeded:
        raise HTTPException(
            status_code=409,
            detail={**body, "message": runtime_error},
        )
    return body


@router.post("/tasks/{task_id}/actions/interrupt")
async def interrupt_task(
    task_id: str,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict:
    return await _run_operator_action(
        task_id=task_id,
        action_type="interrupt",
        idempotency_key=idempotency_key,
        request=request,
    )


@router.post("/tasks/{task_id}/actions/rollback")
async def rollback_task(
    task_id: str,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict:
    return await _run_operator_action(
        task_id=task_id,
        action_type="rollback",
        idempotency_key=idempotency_key,
        request=request,
    )


@router.get("/tasks/{task_id}/agent-release")
async def get_task_agent_release(task_id: str, request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        task = await service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Ansich Task not found")
        binding = await service.get_task_agent_release(task_id)
        drift = await service.get_current_belief(task_id, "configuration_drift")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich Task AgentRelease query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    return {
        "binding": (
            None
            if binding is None
            else {
                "task_id": binding.task_id,
                "relation_role": binding.relation_role,
                "established_obs_id": binding.established_obs_id,
                "release": _safe_release_detail(binding.release),
            }
        ),
        "provider_drift": (None if drift is None else drift.model_dump(mode="json")),
        "projection_status": _projection_status(service),
    }


@router.get("/tasks/{task_id}/children")
async def list_task_children(task_id: str, request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        if await service.get_task(task_id) is None:
            raise HTTPException(status_code=404, detail="Ansich Task not found")
        children = await service.list_task_children(task_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich child Task query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    return {
        "items": [item.model_dump(mode="json") for item in children],
        "projection_status": _projection_status(service),
    }


@router.get("/tasks/{task_id}/tree")
async def get_task_tree(
    task_id: str,
    request: Request,
    direction: TaskTreeDirection = Query(default="both"),
    depth: int = Query(default=4, ge=1, le=32),
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        tree = await service.get_task_tree(
            task_id,
            direction=direction,
            depth=depth,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich Task tree query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    if tree is None:
        raise HTTPException(status_code=404, detail="Ansich Task not found")
    tree_payload = tree.model_dump(mode="json")
    for payload, node in zip(tree_payload["nodes"], tree.nodes, strict=True):
        binding = node.agent_release
        if binding is None:
            continue
        payload["agent_release"] = {
            "task_id": binding.task_id,
            "relation_role": binding.relation_role,
            "established_obs_id": binding.established_obs_id,
            "release": _safe_release_detail(binding.release),
        }
    return {
        "tree": tree_payload,
        "projection_status": _projection_status(service),
    }


@router.get("/tasks/{task_id}/usage")
async def get_task_usage(
    task_id: str,
    request: Request,
    scope: Literal["local", "inclusive"] = Query(default="local"),
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        task = await service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Ansich Task not found")
        usage, breakdown = await asyncio.gather(
            service.get_task_usage(task_id),
            service.get_task_usage_breakdown(task_id, scope=scope),
        )
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
        "scope": scope,
        "values": [item.model_dump(mode="json") for item in (usage.local if scope == "local" else usage.inclusive)],
        "sources": [item.model_dump(mode="json") for item in breakdown.sources],
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
    root_only: bool = Query(default=False),
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
            root_only=root_only,
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
        behavior = await service.get_current_belief(task_id, "behavior")
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"message": "Ansich Task query failed", "projection_status": _projection_status(service)},
        ) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="Ansich Task not found")
    return {
        "task": task.model_dump(mode="json"),
        "behavior": None if behavior is None else behavior.model_dump(mode="json"),
        "projection_status": _projection_status(service),
    }


@router.get("/tasks/{task_id}/scopes")
async def get_task_scopes(task_id: str, request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        if await service.get_task(task_id) is None:
            raise HTTPException(status_code=404, detail="Ansich Task not found")
        scopes = await service.get_task_scopes(task_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich Scope query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    return {
        "scopes": scopes.model_dump(mode="json"),
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
    elif observation.kind == "agent_release.resolved" and isinstance(payload, dict):
        release = payload.get("release")
        manifest = release.get("manifest") if isinstance(release, dict) else None
        if isinstance(manifest, dict) and isinstance(manifest.get("prompt"), dict):
            _redact_release_prompt(manifest)
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


@router.get("/tool-calls/{tool_call_id}/authorization")
async def get_tool_authorization(tool_call_id: str, request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    await _tool_call_or_404(service, tool_call_id)
    try:
        authorization = await service.get_tool_authorization(tool_call_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich authorization query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    return {
        "authorization": (None if authorization is None else authorization.model_dump(mode="json")),
        "projection_status": _projection_status(service),
    }


def _safe_effect_payload(effect) -> dict:
    payload = effect.model_dump(mode="json")
    preview = payload.get("target_preview")
    if not isinstance(preview, str):
        return payload
    if contains_credential_like_material(preview):
        payload["target_preview"] = "<redacted>"
    elif preview.startswith("/"):
        payload["target_preview"] = f"<absolute>/{posixpath.basename(posixpath.normpath(preview))}"
    return payload


@router.get("/tool-calls/{tool_call_id}/effects")
async def get_tool_effects(tool_call_id: str, request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    await _tool_call_or_404(service, tool_call_id)
    try:
        effects = await service.get_tool_effects(tool_call_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich effect query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    return {
        "effects": (
            None
            if effects is None
            else {
                "tool_call_id": effects.tool_call_id,
                "coverage": effects.coverage,
                "effects": [_safe_effect_payload(item) for item in effects.effects],
            }
        ),
        "projection_status": _projection_status(service),
    }


@router.get("/operations/safety-events")
async def list_safety_events(
    request: Request,
    workflow_state: Literal[
        "open",
        "acknowledged",
        "dismissed",
        "resolved",
    ]
    | None = Query(default=None, alias="state"),
    tool_call_id: str | None = Query(default=None, alias="tool_call"),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        pages = await asyncio.gather(
            *(
                service.list_alerts(
                    limit=limit,
                    alert_type=alert_type,
                    workflow_state=workflow_state,
                    task_id=tool_call_id,
                )
                for alert_type in (
                    "attempted_scope_violation",
                    "realized_scope_violation",
                    "unverified_effect",
                )
            )
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich safety event query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    items = sorted(
        (item for page in pages for item in page),
        key=lambda item: (item.updated_at, item.alert_id),
        reverse=True,
    )[:limit]
    return {
        "items": [item.model_dump(mode="json") for item in items],
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
