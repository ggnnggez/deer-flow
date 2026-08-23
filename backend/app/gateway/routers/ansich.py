import asyncio
import base64
import binascii
import hashlib
import json
import logging
import posixpath
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import quote

from ansich.alerts import AlertWorkflowConflict
from ansich.contracts import ControlValue, HardDeleteReport, NamedVersion, Producer, TaskLifecycleScope
from ansich.credentials import contains_credential_like_material
from ansich.errors import HardDeleteError, PayloadExpiredError, RawReadAuditUnavailableError, StorageUnavailableError
from ansich.evaluation import (
    EvaluationDimension,
    EvaluationKind,
    EvaluationRecord,
    EvaluationSubjectType,
    EvaluationVerdict,
    ScoreScale,
)
from ansich.ids import new_id
from ansich.quality import compare_release_quality
from ansich.release import (
    AgentRelease,
    AgentReleaseFingerprint,
    compare_agent_releases,
)
from ansich.task_tree import TaskTreeDirection
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.deps import (
    AnsichEvaluationSettings,
    AnsichRawReadSettings,
    get_current_user_from_request,
    get_run_manager,
    require_admin_user,
    snapshot_ansich_evaluation_settings,
    snapshot_ansich_raw_read_settings,
)
from deerflow.runtime.runs.manager import CancelOutcome
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.trace_context import get_current_trace_id

router = APIRouter(prefix="/api/ansich", tags=["ansich"])
_ADMIN_REQUIRED = "Ansich developer/operator observability requires an admin account."
logger = logging.getLogger(__name__)
#: Identity of evaluations submitted over HTTP rather than by a runtime probe.
_EVALUATION_PRODUCER = Producer(name="ansich-evaluation-api", version="1", instance_id="gateway")
#: The assessor identity of an operator's explicit Alert-dismissal judgement.
_DISMISSAL_ASSESSOR = NamedVersion(name="operator-dismissal", version="1.0.0")
#: Kinds whose replay identity is their suite/case/run tuple, so the contract
#: derives their ``source_event_id`` instead of taking the caller's key. Mirrors
#: the contract's own suite-bound set (``ansich.evaluation``), which is private.
_BENCHMARK_EVALUATION_KINDS: frozenset[str] = frozenset({"benchmark_assertion", "unit_test"})
#: Used only when a request arrives on an app whose lifespan captured nothing —
#: router tests and alternative ASGI compositions. Production always snapshots.
_DEFAULT_EVALUATION_SETTINGS = snapshot_ansich_evaluation_settings(None)
_DEFAULT_RAW_READ_SETTINGS = snapshot_ansich_raw_read_settings(None)
#: Every response the four §7 raw-body *handlers* produce carries it, on the
#: refusals as well as on the served body: a 410 is heuristically cacheable, and
#: a 403 or a 413 still names an id somebody asked for.
#:
#: **Two refusals are produced outside the handler and therefore carry no
#: ``Cache-Control`` at all**, which is why the claim above says "handler" and
#: not "route": an over-long ``purpose`` is refused by FastAPI's own
#: ``RequestValidationError`` handler (422, before the handler runs, reading
#: nothing), and an unauthenticated request by ``AuthMiddleware.dispatch``
#: (401, before ``call_next``). Neither status is in RFC 7231 §6.1's
#: heuristically cacheable set, so a shared cache will not store either absent
#: explicit freshness -- benign, but the invariant is not total and the 422 body
#: echoes the caller's ``purpose`` beside a URL naming a payload id. Closing it
#: would take a route-scoped validation handler or moving the bound into the
#: handler; narrowing the claim is the choice recorded here.
_NO_STORE: dict[str, str] = {"Cache-Control": "no-store"}
#: Bound on the audited free-text ``purpose``. Over it the request is refused by
#: FastAPI's own validation (422) before the handler runs, which reads nothing.
RAW_READ_PURPOSE_MAX_LENGTH = 200
#: Bound on the caller-supplied request correlation copied into the audit row.
_RAW_READ_CORRELATION_MAX_LENGTH = 200
#: The one place the ``purpose`` parameter is declared, so the four routes
#: cannot drift on its name, its optionality or its bound.
_RAW_READ_PURPOSE = Query(
    default=None,
    max_length=RAW_READ_PURPOSE_MAX_LENGTH,
    description="Why this raw body is being read; recorded in the access audit, never interpreted.",
)


def _service_or_503(request: Request):
    service = getattr(request.app.state, "ansich_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Ansich is disabled or unavailable")
    return service


def _expired_payload_410(exc: PayloadExpiredError, *, what: str, actor: str) -> HTTPException:
    """Answer a raw-body read whose evidence expired under retention with 410.

    **410 Gone, not 404** (plan ruling RC6). The two are different answers and
    the difference is the whole reason payload tombstones exist: 404 says this
    evidence has no body — it never was recorded, or the id is wrong — while
    this says it was recorded, it was readable for as long as the configured
    policy kept it, and the policy expired it on the date in the response. A
    reader told 404 goes looking for a bug; a reader told 410 reads the policy.

    The body carries the tombstone's lineage half and nothing else: the digest,
    the size, when it went and under which rule. That is the whole of what can
    still be said truthfully about the bytes, and it is what lets an operator
    tell a retention outcome from a deletion nobody configured.

    **``no-store`` rides on the exception, not on the injected ``Response``.**
    Those routes set the header as their last statement before returning, which
    never executes on a raise — FastAPI builds a fresh response from the
    exception and the injected object's headers are only merged on the success
    path. That gap matters more here than beside the 404 and 503 next to it,
    because **410 is one of the heuristically cacheable statuses** (RFC 7231
    §6.1), so the one new status this family gained is the one where an absent
    ``no-store`` has teeth. The cached body would be lineage rather than
    evidence, so the exposure is small — but "never polled, never cached,
    always logged" is this family's stated discipline and it should be true.
    The actor line is the "always logged" half, for the same reason: a read
    that was refused is still a read that was attempted. It takes the audited
    actor (the object ``require_admin_user`` authorized) rather than re-deriving
    one from the request, so the log line and the §7 audit row cannot name
    different people for the same refusal.
    """

    logger.info(
        "Ansich raw payload read refused: evidence expired under retention",
        extra={
            "ansich_payload_id": exc.payload_id,
            "ansich_retention_policy": exc.policy,
            "ansich_actor_id": actor,
        },
    )
    return HTTPException(
        status_code=410,
        detail={
            "message": f"Ansich {what} expired under the retention policy",
            "payload_id": exc.payload_id,
            "policy": exc.policy,
            "deleted_at": exc.deleted_at.isoformat() if hasattr(exc.deleted_at, "isoformat") else exc.deleted_at,
            "sha256": exc.sha256,
            "byte_size": exc.byte_size,
        },
        headers={"Cache-Control": "no-store"},
    )


def _projection_status(service) -> dict:
    return service.get_health().model_dump(mode="json")


def _evaluation_settings(request: Request) -> AnsichEvaluationSettings:
    """Return the startup snapshot of the evaluation knobs (never a live read)."""

    settings = getattr(request.app.state, "ansich_evaluation_settings", None)
    return settings if settings is not None else _DEFAULT_EVALUATION_SETTINGS


def _raw_read_settings(request: Request) -> AnsichRawReadSettings:
    """Return the startup snapshot of the raw-read size limit (never a live read)."""

    settings = getattr(request.app.state, "ansich_raw_read_settings", None)
    return settings if settings is not None else _DEFAULT_RAW_READ_SETTINGS


def _raw_read_actor(user) -> str:
    """The audited actor id, strict.

    ``require_admin_user`` hands back the very object it authorized, so the
    ``"unknown"`` fallback is unreachable on the allowed path and survives only
    for the denial row, where the caller may not have been stamped.
    """

    identity = getattr(user, "id", None)
    return "unknown" if identity is None else str(identity)


def _request_correlation_id(request: Request) -> str | None:
    """The request correlation spec:112 asks the audit to carry.

    The bound trace id first (``deerflow.trace_context``, which the Gateway's
    ``TraceMiddleware`` sets from a valid inbound ``X-Trace-Id`` or mints), and
    the raw inbound header as the fallback — because trace correlation is gated
    on ``logging.enhance.enabled`` and an operator who left it off still sends
    the header. The fallback value is caller-supplied text, so it is bounded
    and recorded exactly as received: it correlates a request, it authenticates
    nothing.
    """

    correlation = get_current_trace_id() or request.headers.get("X-Trace-Id")
    if not correlation:
        return None
    return correlation[:_RAW_READ_CORRELATION_MAX_LENGTH]


@dataclass
class _RawReadAudit:
    """One in-flight audited read: its identity, and its terminal row."""

    service: object
    read_id: str
    actor: str
    target_kind: str
    target_id: str
    purpose: str | None
    correlation_id: str | None

    async def finish(self, *, outcome: str, http_status: int, served_byte_size: int | None = None) -> None:
        """Record how the read ended. Degrades to a WARNING, deliberately.

        The asymmetry with the requested row is the point. That row is the
        access record and is written *before* the body is touched, so refusing
        the read when it fails costs nothing that was already disclosed. By the
        time this runs the read has happened and is on record with an actor, a
        target and a time; failing the response now would report a served read
        as an error while disclosing it anyway. So the outcome half degrades and
        says so — an audit trail that knows a read happened but not how it ended
        is strictly better than one that lies about either.
        """

        try:
            await self.service.audit_raw_payload_read(  # type: ignore[attr-defined]
                status="succeeded" if outcome == "served" else "failed",
                read_id=self.read_id,
                actor=self.actor,
                target_kind=self.target_kind,
                target_id=self.target_id,
                purpose=self.purpose,
                request_correlation_id=self.correlation_id,
                outcome=outcome,
                http_status=http_status,
                served_byte_size=served_byte_size,
            )
        except Exception:
            logger.warning(
                "Ansich raw-read outcome could not be audited; the access itself is on record",
                extra={
                    "ansich_target_kind": self.target_kind,
                    "ansich_target_id": self.target_id,
                    "ansich_actor_id": self.actor,
                    "ansich_raw_read_outcome": outcome,
                },
                exc_info=True,
            )


async def _admin_raw_reader(
    request: Request,
    *,
    target_kind: str,
    target_id: str,
    purpose: str | None,
):
    """The admin gate for a raw-body read: **a denial is audited, not read.**

    Spec:113 in one sentence — a refused request enters the audit trail, and
    nothing may read the payload in order to record that refusal. Both halves
    are structural here: this runs before any service read, and what it writes
    is one terminal ``operator.action_failed`` row rather than a
    requested/terminal pair, because no read was ever attempted.

    **The denial audit is best-effort and that is not a hole in the fail-closed
    rule.** The rule protects *disclosure*: an unaudited read must not happen.
    A denial discloses nothing, so refusing the request a second time because
    its refusal could not be recorded would trade a logged gap for an outage
    while protecting nobody. The gap is logged at WARNING.
    """

    try:
        return await require_admin_user(request, detail=_ADMIN_REQUIRED)
    except HTTPException as denied:
        service = getattr(request.app.state, "ansich_service", None)
        if denied.status_code == 403 and service is not None:
            user = getattr(request.state, "user", None)
            try:
                await service.audit_raw_payload_read(
                    status="failed",
                    read_id=new_id(),
                    actor=_raw_read_actor(user),
                    target_kind=target_kind,
                    target_id=target_id,
                    purpose=purpose,
                    request_correlation_id=_request_correlation_id(request),
                    outcome="denied_not_admin",
                    http_status=denied.status_code,
                )
            except Exception:
                logger.warning(
                    "Ansich raw-read denial could not be audited",
                    extra={"ansich_target_kind": target_kind, "ansich_target_id": target_id},
                    exc_info=True,
                )
        raise HTTPException(
            status_code=denied.status_code,
            detail=denied.detail,
            headers={**(denied.headers or {}), **_NO_STORE},
        ) from denied


async def _open_audited_raw_read(
    request: Request,
    *,
    target_kind: str,
    target_id: str,
    purpose: str | None,
) -> tuple[object, _RawReadAudit]:
    """Admin gate, then subject resolution, then the durable requested audit.

    The order is the whole contract (plan ruling RC9): the caller is
    authorized, the audit row for the attempt is **committed**, and only then
    does the route ask the store for a body. Every step before the return
    reads ids and health, never a payload.

    A caller that gets past here has an audit row on disk saying it did.
    """

    user = await _admin_raw_reader(request, target_kind=target_kind, target_id=target_id, purpose=purpose)
    try:
        service = _service_or_503(request)
        _ensure_queryable(service)
    except HTTPException as unavailable:
        # These two refuse before there is anything to audit — a disabled
        # service and an unreadable store both mean no body was fetched and
        # none could have been recorded — but they are still answers these
        # routes give, and "every answer from this family is `no-store`" is a
        # rule worth being able to state without exceptions.
        raise HTTPException(
            status_code=unavailable.status_code,
            detail=unavailable.detail,
            headers={**(unavailable.headers or {}), **_NO_STORE},
        ) from unavailable
    audit = _RawReadAudit(
        service=service,
        read_id=new_id(),
        actor=_raw_read_actor(user),
        target_kind=target_kind,
        target_id=target_id,
        purpose=purpose,
        correlation_id=_request_correlation_id(request),
    )
    try:
        await service.audit_raw_payload_read(
            status="requested",
            read_id=audit.read_id,
            actor=audit.actor,
            target_kind=target_kind,
            target_id=target_id,
            purpose=purpose,
            request_correlation_id=audit.correlation_id,
        )
    except RawReadAuditUnavailableError as unavailable:
        # §7 FAIL-CLOSED — the batch's ONE documented inversion of the
        # project-wide fail-open rule (spec:114, plan Global Constraint 1).
        # Everything else Ansich collects degrades quietly rather than break a
        # caller; here the audit *is* the security control, so a read whose
        # access record did not land must not happen. Do not "fix" this into a
        # warning: the payload has not been touched at this point, and the
        # whole value of that ordering is that this branch can still refuse.
        logger.warning(
            "Ansich raw payload read refused: the access audit could not be persisted",
            extra={"ansich_target_kind": target_kind, "ansich_target_id": target_id, "ansich_actor_id": audit.actor},
            exc_info=True,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich raw payload read refused: the access audit could not be persisted",
                "projection_status": _projection_status(service),
            },
            headers=_NO_STORE,
        ) from unavailable
    return service, audit


def _raw_read_byte_size(document: object) -> int:
    """The size of the inner document, which bounds the response approximately.

    **Not a Content-Length ceiling**, and the two deviations run in opposite
    directions so neither cancels the other reliably. (a) ``json.dumps``
    defaults to ``(", ", ": ")`` while Starlette's ``JSONResponse.render`` uses
    the compact separators, so this **over**-counts by a byte per separator and
    a structure-heavy body is refused slightly early. (b) ``document`` is the
    payload alone — the response envelope (``{"payload": …}``, the release
    wrapper, and on the ToolCall routes the whole ``{role}_result`` block beside
    it) is **not** measured, so the served response is larger than the number
    checked here. ``ensure_ascii=False`` is deliberate and does match Starlette.
    """

    return len(json.dumps(document, default=str, ensure_ascii=False).encode("utf-8"))


async def _enforce_raw_read_limit(request: Request, audit: _RawReadAudit, *, document: object) -> int:
    """Refuse a body over ``ansich.raw_read_max_bytes`` — 413, audited.

    The limit is on the **response**, which is why it is measured after the
    store answered rather than guessed from a column: bulk raw export is out of
    scope for v1 (spec:118) and this is what keeps a single read from becoming
    one. The refusal is a first-class audited outcome, so an operator who tried
    to pull a 40 MiB tool result is on record as having tried.
    """

    size = _raw_read_byte_size(document)
    limit = _raw_read_settings(request).max_bytes
    if size > limit:
        await audit.finish(outcome="oversize", http_status=413, served_byte_size=None)
        raise HTTPException(
            status_code=413,
            detail={
                "message": "Ansich raw payload is larger than ansich.raw_read_max_bytes",
                "byte_size": size,
                "limit_bytes": limit,
            },
            headers=_NO_STORE,
        )
    return size


def _apply_raw_read_headers(response: Response, *, content_type: str | None, filename: str) -> None:
    """``no-store`` always; ``attachment`` for anything that is not JSON.

    The artifacts router's precedent, applied one layer in. The body travels
    inside a JSON document, so a browser will not render it directly — but the
    declared content type is attacker-influenced data that came out of a tool
    result, and the rule there ("active content is a download, never a render")
    is cheap to keep true here rather than argued away per content type.
    """

    response.headers.update(_NO_STORE)
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized and normalized != "application/json" and not normalized.endswith("+json"):
        response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"


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


class AlertSemanticOverride(BaseModel):
    """An operator's explicit quality judgement attached to a dismissal.

    Optional by design: an ordinary acknowledge or dismiss is an operational
    decision about the Alert, not a semantic claim about the Task, and must
    leave the quality Beliefs untouched (spec section 5).
    """

    model_config = ConfigDict(extra="forbid")

    dimension: Literal[
        "correctness",
        "completeness",
        "relevance",
        "safety",
        "efficiency",
    ]
    verdict: Literal["pass", "fail", "partial"]
    rationale: str | None = None


class AlertDismissRequest(AlertWorkflowRequest):
    reason: str = Field(min_length=1, max_length=512)
    semantic_override: AlertSemanticOverride | None = None


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
    cohort: str | None = Query(default=None),
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    settings = _evaluation_settings(request)
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
    try:
        left_quality = await service.get_release_quality(left, cohort_key=cohort)
        right_quality = await service.get_release_quality(right, cohort_key=cohort)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich AgentRelease quality comparison query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    comparison = compare_agent_releases(
        _release_from_detail(left_detail),
        _release_from_detail(right_detail),
    )
    # A release nobody evaluated compares as absent quality, never as a missing
    # release: the structural comparison above stays available either way.
    comparisons = compare_release_quality(
        () if left_quality is None else left_quality.cohorts,
        () if right_quality is None else right_quality.cohorts,
        min_samples=settings.min_cohort_samples,
        unexplained_loss=service.get_health().loss_detected,
        # The store's own active selection, not the build's constant: since the
        # active-version row exists those are two different facts, and stamping
        # the constant made this field a claim nobody had checked. The read is
        # fail-open and served from the same per-process cache the write path
        # uses, so it cannot fail the comparison or disagree with it.
        resolver=await service.get_active_resolver(),
    )
    return {
        "comparison": comparison.model_dump(mode="json"),
        "quality": {
            "comparisons": [item.model_dump(mode="json") for item in comparisons],
            "cohort": cohort,
        },
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
    purpose: str | None = _RAW_READ_PURPOSE,
) -> dict:
    """Return the complete sanitized manifest through an audited, non-cached path.

    One of the four §7 raw-body routes: admin, subject-resolved, audited before
    the read and again after it, ``no-store`` on every answer it can give.
    """

    service, audit = await _open_audited_raw_read(
        request,
        target_kind="agent_release",
        target_id=release_id,
        purpose=purpose,
    )
    try:
        detail = await service.get_agent_release(release_id)
    except Exception as exc:
        await audit.finish(outcome="read_failed", http_status=503)
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich AgentRelease manifest query failed",
                "projection_status": _projection_status(service),
            },
            headers=_NO_STORE,
        ) from exc
    if detail is None:
        await audit.finish(outcome="not_found", http_status=404)
        raise HTTPException(status_code=404, detail="Ansich AgentRelease not found", headers=_NO_STORE)
    manifest = detail.manifest.model_dump(mode="json")
    served_byte_size = await _enforce_raw_read_limit(request, audit, document=manifest)
    logger.info(
        "Ansich raw AgentRelease manifest accessed",
        extra={"ansich_release_id": release_id, "ansich_actor_id": audit.actor},
    )
    _apply_raw_read_headers(response, content_type="application/json", filename=f"{release_id}.json")
    await audit.finish(outcome="served", http_status=200, served_byte_size=served_byte_size)
    return {"release_id": release_id, "manifest": manifest}


@router.get("/agent-releases/{release_id}/quality")
async def get_agent_release_quality(
    release_id: str,
    request: Request,
    cohort: str | None = Query(default=None),
) -> dict:
    """Return one AgentRelease's aggregated semantic quality cells."""

    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        quality = await service.get_release_quality(release_id, cohort_key=cohort)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich AgentRelease quality query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    if quality is None:
        raise HTTPException(status_code=404, detail="Ansich AgentRelease not found")
    return {
        "release_id": quality.release_id,
        "cohorts": [cohort_view.model_dump(mode="json") for cohort_view in quality.cohorts],
        "projection_status": _projection_status(service),
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
        "environment_pressure",
        "environment_leak_suspected",
        # Phase 11 (RB3): the two process-subject types. Both are produced by
        # the periodic operations pass against the host Scope, so an operator
        # filtering by them gets process health rather than one Task's.
        "projection_failure",
        "observability_degradation",
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


async def _record_dismissal_override(
    service,
    *,
    alert_id: str,
    alert,
    override: AlertSemanticOverride,
) -> dict:
    """Record the operator's semantic judgement for an already-dismissed Alert.

    Best-effort on purpose: the workflow write has already succeeded, so a
    failure here degrades the extra assertion instead of retracting a dismissal
    the operator can no longer repeat (the next attempt hits a version
    conflict). The Alert's subject is only the owning Task for Task-scoped
    Alerts — a ToolCall-scoped one (the scope-safety types) carries no Task in
    its summary, so it degrades rather than attaching a Task-level quality
    Belief to a ToolCall id.
    """

    try:
        subject_type = await service.get_evaluation_subject(alert.subject_id)
        if subject_type != "task":
            return {"status": "degraded", "reason": "alert_subject_is_not_a_task", "evaluation": None}
        receipt = await service.record_evaluation(
            EvaluationRecord(
                subject_type="task",
                subject_id=alert.subject_id,
                task_id=alert.subject_id,
                evaluation_kind="developer_annotation",
                dimension=override.dimension,
                verdict=override.verdict,
                rationale=override.rationale,
                assessor=_DISMISSAL_ASSESSOR,
                fidelity_class="soft",
                human_override=True,
                occurred_at=datetime.now(UTC),
            ),
            # The dismissal that produced this workflow version is the replay
            # identity, matching the workflow Observation's own stable id.
            source_event_id=f"evaluation:dismiss:{alert_id}:{alert.workflow_version}",
            producer=_EVALUATION_PRODUCER,
        )
    except Exception:
        logger.exception(
            "Ansich Alert dismissal semantic override failed",
            extra={"ansich_alert_id": alert_id},
        )
        return {"status": "degraded", "reason": "evaluation_write_failed", "evaluation": None}
    return {
        "status": "recorded",
        "reason": None,
        "evaluation": receipt.model_dump(mode="json"),
    }


async def _change_alert_workflow(
    *,
    alert_id: str,
    action: Literal["acknowledge", "dismiss"],
    workflow_version: int,
    reason: str | None,
    request: Request,
    semantic_override: AlertSemanticOverride | None = None,
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
    payload = {
        "alert": alert.model_dump(mode="json"),
        "projection_status": _projection_status(service),
    }
    if semantic_override is not None:
        # Additive field: consumers of the existing two keys are untouched.
        payload["semantic_override"] = await _record_dismissal_override(
            service,
            alert_id=alert_id,
            alert=alert,
            override=semantic_override,
        )
    return payload


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
        semantic_override=body.semantic_override,
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
    # A `requested` row is deliberately not rejected here. Whether it is still an
    # in-flight duplicate or an orphan a crash stranded between begin and finish is
    # one decision, and `begin_operator_action` owns it atomically below so two
    # concurrent retries cannot both take the same orphan over. The in-progress 409
    # for a still-fresh attempt comes back from that same conflict election.
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
    by: Literal["model"] | None = Query(default=None),
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    # The by-model breakdown is computed from the Task's own LLM attempts, so
    # it has no inclusive form: a descendant's attempts belong to that Task.
    if by == "model" and scope == "inclusive":
        raise HTTPException(status_code=422, detail="by=model supports local scope only")
    try:
        task = await service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Ansich Task not found")
        usage, breakdown = await asyncio.gather(
            service.get_task_usage(task_id),
            service.get_task_usage_breakdown(task_id, scope=scope),
        )
        by_model = await service.get_task_usage_by_model(task_id) if by == "model" else []
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
    payload = {
        "usage": usage.model_dump(mode="json"),
        "scope": scope,
        "values": [item.model_dump(mode="json") for item in (usage.local if scope == "local" else usage.inclusive)],
        "sources": [item.model_dump(mode="json") for item in breakdown.sources],
        "projection_status": _projection_status(service),
    }
    # Additive: without ?by=model the response is unchanged, key order included.
    if by == "model":
        payload["by_model"] = [item.model_dump(mode="json") for item in by_model]
    return payload


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


@router.get("/tasks/{task_id}/environment")
async def get_task_environment(task_id: str, request: Request) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        environment = await service.get_task_environment(task_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich Environment query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    return environment.model_dump(mode="json")


@router.get("/scopes/{scope_id}/environment/history")
async def get_environment_history(
    scope_id: str,
    request: Request,
    environment_scope: Literal["container", "process_group", "host_shared"] = Query(),
    metric: str = Query(pattern=r"^[a-z][a-z0-9_]{0,63}$"),
    window_minutes: int = Query(default=60, ge=1, le=1440),
    max_points: int = Query(default=360, ge=1, le=1000),
) -> dict:
    """One metric's bounded recent trend on one Scope.

    Lazy and metadata-only, like the other trend/detail reads: nothing polls
    it, and a sample that never reported ``metric`` is absent from the series
    rather than present as a zero.
    """

    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        history = await service.get_environment_history(
            scope_id,
            environment_scope=environment_scope,
            metric=metric,
            window_minutes=window_minutes,
            max_points=max_points,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich Environment history query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    return history.model_dump(mode="json")


@router.get("/tasks/{task_id}/environment/tool-samples")
async def get_task_tool_env_samples(task_id: str, request: Request) -> dict:
    """The Task's per-command environment samples, in execution order."""

    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        samples = await service.get_task_tool_env_samples(task_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich Environment tool-sample query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    return samples.model_dump(mode="json")


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


class EvaluationRecordRequest(BaseModel):
    """One submitted evaluation, carrying every EvaluationRecord field.

    ``task_id`` is the only difference from the contract record: a Task subject
    always evaluates its own Task, so the owning Task is derived from the
    subject and an explicit, disagreeing value is rejected rather than
    silently preferred. Every other subject must name its Task. Unknown fields
    are refused like the contract record refuses them, so a misspelled verdict
    or rationale is reported instead of silently dropped.
    """

    model_config = ConfigDict(extra="forbid")

    subject_type: EvaluationSubjectType
    subject_id: str = Field(min_length=1)
    task_id: str | None = Field(default=None, min_length=1)
    evaluation_kind: EvaluationKind
    dimension: EvaluationDimension
    verdict: EvaluationVerdict | None = None
    score: float | None = None
    scale: ScoreScale | None = None
    expected: str | None = None
    actual: str | None = None
    rationale: str | None = None
    assessor: NamedVersion
    fidelity_class: Literal["hard", "rule", "soft"]
    human_override: bool = False
    cohort_key: str | None = None
    suite: str | None = None
    suite_version: str | None = None
    case_id: str | None = None
    run_id: str | None = None
    occurred_at: datetime

    def to_record(self) -> EvaluationRecord:
        """Resolve the owning Task and validate through the contract."""

        if self.subject_type == "task":
            if self.task_id is not None and self.task_id != self.subject_id:
                raise ValueError("a task-subject evaluation derives task_id from subject_id")
            task_id = self.subject_id
        elif self.task_id is None:
            raise ValueError("an evaluation of a non-task subject requires task_id")
        else:
            task_id = self.task_id
        return EvaluationRecord(
            subject_type=self.subject_type,
            subject_id=self.subject_id,
            task_id=task_id,
            evaluation_kind=self.evaluation_kind,
            dimension=self.dimension,
            verdict=self.verdict,
            score=self.score,
            scale=self.scale,
            expected=self.expected,
            actual=self.actual,
            rationale=self.rationale,
            assessor=self.assessor,
            fidelity_class=self.fidelity_class,
            human_override=self.human_override,
            cohort_key=self.cohort_key,
            suite=self.suite,
            suite_version=self.suite_version,
            case_id=self.case_id,
            run_id=self.run_id,
            occurred_at=self.occurred_at,
        )


def _canonical_evaluation_payload_size(record: EvaluationRecord) -> int:
    """Measure the Observation payload exactly as storage will encode it."""

    payload = {"evaluation": record.model_dump(mode="json")}
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"))


@router.post("/evaluations")
async def record_evaluation(
    body: EvaluationRecordRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict:
    """Record one evaluation and report where its projection currently stands."""

    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    if not idempotency_key.strip() or len(idempotency_key) > 128:
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key must contain 1 to 128 characters",
        )
    service = _service_or_503(request)
    _ensure_queryable(service)
    settings = _evaluation_settings(request)
    try:
        record = body.to_record()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload_bytes = _canonical_evaluation_payload_size(record)
    if payload_bytes > settings.max_payload_bytes:
        raise HTTPException(
            status_code=413,
            detail={
                "message": "Ansich evaluation payload is too large",
                "payload_bytes": payload_bytes,
                "limit_bytes": settings.max_payload_bytes,
            },
        )
    try:
        entity_type = await service.get_evaluation_subject(record.subject_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich evaluation subject query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    if entity_type is None:
        raise HTTPException(status_code=404, detail="Ansich evaluation subject not found")
    if entity_type != record.subject_type:
        raise HTTPException(
            status_code=422,
            detail=f"Ansich evaluation subject is a {entity_type}, not a {record.subject_type}",
        )
    try:
        receipt = await service.record_evaluation(
            record,
            # A suite-bound evaluation replays on its own suite/case/run tuple,
            # so the contract derives that identity instead of the caller key.
            source_event_id=(None if record.evaluation_kind in _BENCHMARK_EVALUATION_KINDS else f"evaluation:api:{idempotency_key}"),
            producer=_EVALUATION_PRODUCER,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StorageUnavailableError as exc:
        # The replay lookup could not be answered, so the contract deliberately
        # refuses to guess (F10-25): it neither calls the evaluation `failed` --
        # that would report ignorance as knowledge -- nor skips the dedupe and
        # records a second Observation. `_ensure_queryable` above cannot see
        # this: its health read is process-local and still says storage is
        # available. The clause is explicit so this stays the *named* condition
        # rather than sharing a mapping with any unexpected failure below.
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich storage is unavailable",
                "projection_status": _projection_status(service),
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich evaluation write failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    return receipt.model_dump(mode="json")


@router.get("/tasks/{task_id}/evaluations")
async def list_task_evaluations(task_id: str, request: Request) -> dict:
    """Return one Task's quality Beliefs plus the evaluations behind them."""

    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        task = await service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Ansich Task not found")
        beliefs = await service.get_quality_beliefs(task_id)
        evaluations = await service.list_evaluations(task_id=task_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich evaluation query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    return {
        "task_id": task_id,
        "quality_beliefs": [belief.model_dump(mode="json") for belief in beliefs],
        "evaluations": [item.model_dump(mode="json") for item in evaluations],
        "projection_status": _projection_status(service),
    }


@router.get("/steps/{step_id}/evaluations")
async def list_step_evaluations(step_id: str, request: Request) -> dict:
    """Return the evaluations recorded against one Step."""

    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        if await service.get_evaluation_subject(step_id) != "step":
            raise HTTPException(status_code=404, detail="Ansich Step not found")
        evaluations = await service.list_evaluations(subject_type="step", subject_id=step_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich evaluation query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    return {
        "step_id": step_id,
        "evaluations": [item.model_dump(mode="json") for item in evaluations],
        "projection_status": _projection_status(service),
    }


@router.get("/evaluations/{obs_id}/payload")
async def get_evaluation_payload(
    obs_id: str,
    request: Request,
    response: Response,
    purpose: str | None = _RAW_READ_PURPOSE,
) -> dict:
    """Return one evaluation Observation's full payload after an explicit read.

    The list endpoints project metadata only; ``expected``/``actual``/
    ``rationale`` are bodies and follow the same rule as raw Tool and
    ContentBlock payloads — never polled, never cached, always audited (§7).
    """

    service, audit = await _open_audited_raw_read(
        request,
        target_kind="evaluation",
        target_id=obs_id,
        purpose=purpose,
    )
    try:
        payload = await service.get_evaluation_observation_payload(obs_id)
    except PayloadExpiredError as expired:
        await audit.finish(outcome="expired", http_status=410)
        raise _expired_payload_410(expired, what="evaluation payload", actor=audit.actor) from expired
    except Exception as exc:
        await audit.finish(outcome="read_failed", http_status=503)
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich evaluation payload query failed",
                "projection_status": _projection_status(service),
            },
            headers=_NO_STORE,
        ) from exc
    if payload is None:
        await audit.finish(outcome="not_found", http_status=404)
        raise HTTPException(status_code=404, detail="Ansich evaluation payload not found", headers=_NO_STORE)
    served_byte_size = await _enforce_raw_read_limit(request, audit, document=payload)
    logger.info(
        "Ansich evaluation payload accessed",
        extra={"ansich_evaluation_obs_id": obs_id, "ansich_actor_id": audit.actor},
    )
    _apply_raw_read_headers(response, content_type="application/json", filename=f"{obs_id}.json")
    await audit.finish(outcome="served", http_status=200, served_byte_size=served_byte_size)
    return {"evaluation_obs_id": obs_id, "payload": payload}


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
    try:
        environment_sample = await service.get_tool_environment_sample(tool_call_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich ToolCall query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    return {
        "tool_call": tool_call.model_dump(mode="json"),
        # Additive: null when no per-command environment sample was recorded
        # for this ToolCall; existing fields are unchanged.
        "environment_sample": (None if environment_sample is None else environment_sample.model_dump(mode="json")),
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


@router.get("/operations/failed-jobs")
async def list_failed_jobs(
    request: Request,
    task_id: str | None = Query(default=None, alias="task"),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        jobs = await service.list_failed_jobs(task_id=task_id, limit=limit)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich failed-job query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    return {
        "items": [item.model_dump(mode="json") for item in jobs],
        "projection_status": _projection_status(service),
    }


@router.get("/operations/failed-jobs/{job_id}")
async def get_failed_job_detail(
    job_id: str,
    request: Request,
    kind: Literal["projection", "assessor"] = Query(...),
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        detail = await service.get_failed_job_detail(job_id=job_id, kind=kind)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich failed-job detail query failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="Ansich failed job not found")
    return {
        "job": detail.model_dump(mode="json"),
        "projection_status": _projection_status(service),
    }


@router.post("/operations/failed-jobs/retry")
async def retry_failed_jobs(
    request: Request,
    task_id: str | None = Query(default=None, alias="task"),
) -> dict:
    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        retried = await service.retry_failed_projections(task_id=task_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich failed-job retry failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    # Both halves, because ``retried`` alone has always been a re-arm count and
    # never a completion claim: a re-armed job is projected afterwards by
    # whichever worker's loop gets to it. ``unsettled`` is what an operator has
    # to read beside it before concluding the failures are gone -- see
    # ``ansich.contracts.RetryOutcome`` for the lower-bound caveat that applies
    # to it.
    return {
        "retried": retried.re_armed,
        "unsettled": retried.unsettled,
        "projection_status": _projection_status(service),
    }


class HardDeleteRequest(BaseModel):
    """The one thing an owner erasure needs: which Scope."""

    model_config = ConfigDict(extra="forbid")

    scope_id: str = Field(min_length=1, max_length=36, description="The owner or thread Scope entity id to erase")


@router.post("/retention/hard-delete")
async def hard_delete_scope(body: HardDeleteRequest, request: Request) -> dict:
    """Erase one owner/thread Scope and everything inside it (spec §6 D6-2).

    **This one is a route, and the §5 rule it looks like it breaks does not
    apply.** That rule forbids an endpoint that runs an arbitrary projector on
    demand; this is an owner-initiated data action with a fixed, named effect,
    which is the shape §6 asks for -- there is no way to answer "delete my
    thread" from a CLI-only seam.

    Refusals are typed at the store and answered as **409** rather than 400: the
    request is well-formed and the *state* is what refuses (this Scope is a
    parent, is the host anchor, or is a kind shared across owners), except
    ``unknown_scope`` which is a plain 404. ``blocked`` is 409 too and carries
    ``blocker`` **and the committed counts**, because a caller that resolves the
    named referrer and re-runs the same call finishes the erasure -- the
    operation resumes from the store rather than from a cursor, and the Scope
    row it resumes through is still there (the final phase rolls its own delete
    back when it refuses).

    Logged at WARNING with the actor and the counts. An owner erasure is
    irreversible and is the one operation whose *absence* from the record cannot
    be reconstructed afterwards from the rows it removed.
    """

    user = await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    _ensure_queryable(service)
    try:
        report = await service.hard_delete_scope(body.scope_id)
    except HardDeleteError as exc:
        logger.warning(
            "Ansich hard delete refused",
            extra={
                "ansich_scope_id": exc.scope_id,
                "ansich_hard_delete_refusal": exc.reason,
                "ansich_hard_delete_blocker": exc.blocker,
                "ansich_actor": str(getattr(user, "id", "unknown")),
            },
        )
        # The committed counts ride along on a `blocked` refusal, because that
        # is the one refusal raised after work has landed: a caller told only
        # "blocked" has no way to learn that most of the owner's data is
        # already gone, and would read a resumable state as "nothing happened".
        partial = exc.report.model_dump(mode="json") if isinstance(exc.report, HardDeleteReport) else None
        raise HTTPException(
            status_code=404 if exc.reason == "unknown_scope" else 409,
            detail={
                "message": str(exc),
                "reason": exc.reason,
                "blocker": exc.blocker,
                "report": partial,
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Ansich hard delete failed",
                "projection_status": _projection_status(service),
            },
        ) from exc
    logger.warning(
        "Ansich hard delete completed",
        extra={
            "ansich_scope_id": body.scope_id,
            "ansich_actor": str(getattr(user, "id", "unknown")),
            "ansich_hard_delete_report": report.model_dump(mode="json"),
        },
    )
    return {
        "report": report.model_dump(mode="json"),
        "projection_status": _projection_status(service),
    }


async def _get_tool_result_payload(
    *,
    tool_call_id: str,
    role: str,
    request: Request,
    response: Response,
    purpose: str | None,
) -> dict:
    """The shared body of the two ToolCall raw-body routes (§7).

    The ToolCall lookup that used to run before anything else now runs
    **after** the requested-audit row is committed. That is not a reordering
    for its own sake: the audit's subject resolution already asked the store
    who owns this ToolCall, so doing the metadata read first would have put a
    store read ahead of the access record for no gain, and an id that resolves
    to nothing is exactly the probe an auditor wants to see recorded.
    """

    service, audit = await _open_audited_raw_read(
        request,
        target_kind="tool_call",
        target_id=tool_call_id,
        purpose=purpose,
    )
    try:
        tool_call = await _tool_call_or_404(service, tool_call_id)
    except HTTPException as failed:
        await audit.finish(
            outcome="not_found" if failed.status_code == 404 else "read_failed",
            http_status=failed.status_code,
        )
        raise HTTPException(status_code=failed.status_code, detail=failed.detail, headers=_NO_STORE) from failed
    results = tool_call.raw_results if role == "raw" else tool_call.visible_results
    if not results:
        await audit.finish(outcome="not_found", http_status=404)
        raise HTTPException(
            status_code=404,
            detail=f"Ansich ToolCall {role} result not found",
            headers=_NO_STORE,
        )
    result = results[-1]
    try:
        payload = await service.get_content_block_payload(result.content_block_id)
    except PayloadExpiredError as expired:
        await audit.finish(outcome="expired", http_status=410)
        raise _expired_payload_410(expired, what=f"ToolCall {role} payload", actor=audit.actor) from expired
    except Exception as exc:
        await audit.finish(outcome="read_failed", http_status=503)
        raise HTTPException(
            status_code=503,
            detail={
                "message": f"Ansich {role} tool result query failed",
                "projection_status": _projection_status(service),
            },
            headers=_NO_STORE,
        ) from exc
    if payload is None:
        await audit.finish(outcome="not_found", http_status=404)
        raise HTTPException(
            status_code=404,
            detail=f"Ansich ToolCall {role} payload not found",
            headers=_NO_STORE,
        )
    document = payload.model_dump(mode="json")
    served_byte_size = await _enforce_raw_read_limit(request, audit, document=document)
    logger.info(
        "Ansich %s tool result accessed",
        role,
        extra={
            "ansich_tool_call_id": tool_call_id,
            "ansich_block_id": result.content_block_id,
            "ansich_result_role": role,
            "ansich_actor_id": audit.actor,
        },
    )
    _apply_raw_read_headers(
        response,
        content_type=getattr(payload, "content_type", None),
        filename=f"{result.content_block_id}.{role}",
    )
    await audit.finish(outcome="served", http_status=200, served_byte_size=served_byte_size)
    return {
        f"{role}_result": result.model_dump(mode="json"),
        f"{role}_payload": document,
    }


@router.get("/tool-calls/{tool_call_id}/raw-result")
async def get_tool_raw_result(
    tool_call_id: str,
    request: Request,
    response: Response,
    purpose: str | None = _RAW_READ_PURPOSE,
) -> dict:
    return await _get_tool_result_payload(
        tool_call_id=tool_call_id,
        role="raw",
        request=request,
        response=response,
        purpose=purpose,
    )


@router.get("/tool-calls/{tool_call_id}/visible-result")
async def get_tool_visible_result(
    tool_call_id: str,
    request: Request,
    response: Response,
    purpose: str | None = _RAW_READ_PURPOSE,
) -> dict:
    return await _get_tool_result_payload(
        tool_call_id=tool_call_id,
        role="visible",
        request=request,
        response=response,
        purpose=purpose,
    )


@router.get("/content-blocks/{block_id}/payload")
async def get_content_block_payload(
    block_id: str,
    request: Request,
    response: Response,
    purpose: str | None = _RAW_READ_PURPOSE,
) -> dict:
    """Return one ContentBlock's raw body (§7): audited, bounded, ``no-store``."""

    service, audit = await _open_audited_raw_read(
        request,
        target_kind="content_block",
        target_id=block_id,
        purpose=purpose,
    )
    try:
        payload = await service.get_content_block_payload(block_id)
    except PayloadExpiredError as expired:
        await audit.finish(outcome="expired", http_status=410)
        raise _expired_payload_410(expired, what="ContentBlock payload", actor=audit.actor) from expired
    except Exception as exc:
        await audit.finish(outcome="read_failed", http_status=503)
        raise HTTPException(
            status_code=503,
            detail={"message": "Ansich raw payload query failed", "projection_status": _projection_status(service)},
            headers=_NO_STORE,
        ) from exc
    if payload is None:
        await audit.finish(outcome="not_found", http_status=404)
        raise HTTPException(status_code=404, detail="Ansich ContentBlock payload not found", headers=_NO_STORE)
    document = payload.model_dump(mode="json")
    served_byte_size = await _enforce_raw_read_limit(request, audit, document=document)
    logger.info(
        "Ansich raw content payload accessed",
        extra={"ansich_block_id": block_id, "ansich_actor_id": audit.actor},
    )
    _apply_raw_read_headers(response, content_type=getattr(payload, "content_type", None), filename=f"{block_id}.raw")
    await audit.finish(outcome="served", http_status=200, served_byte_size=served_byte_size)
    return {"payload": document}


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
    """Process health plus the additive database block, merged here (RB7③).

    The merge lives at the route rather than inside ``get_health()`` because
    that method is synchronous, runs under the collector's lock and does zero
    IO — a database round trip there would sit on the collection hot path.

    The two halves fail independently, and that is the property this endpoint
    exists for: when storage is down the ``database`` block reads
    ``unreachable`` and every process-side field is still served in full. This
    stays the one Ansich route that answers while storage cannot.

    The merge is a **whole-block passthrough**, deliberately: additive fields
    on ``DatabaseHealth`` (``active_versions`` is the current one) reach the
    client without a second edit here, and — more importantly — a block's
    reachability and its contents can never be assembled from two different
    reads and disagree.
    """

    await require_admin_user(request, detail=_ADMIN_REQUIRED)
    service = _service_or_503(request)
    health = service.get_health().model_dump(mode="json")
    database = await service.get_database_health()
    return {**health, "database": database.model_dump(mode="json")}
