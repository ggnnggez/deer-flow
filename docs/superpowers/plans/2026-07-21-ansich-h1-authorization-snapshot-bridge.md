# H1 Authorization Snapshot Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Ansich's `AuthorizationSnapshot` carry the real `GuardrailMiddleware` decision (policy id/version/decision/reason codes) when guardrails evaluated a tool call, and record `decision="unknown"` when no authorization layer ran.

**Architecture:** A neutral `deerflow.authz.outcome` contract carries a per-tool-call `AuthorizationOutcome` through the per-run `runtime.context` under a `__`-prefixed key. `GuardrailMiddleware` (chain-outer of Ansich's raw probe, chain-inner of Ansich's visible probe) writes the outcome before it returns/hands off; the two Ansich `_record_authorization` call sites pop it (pop-on-read) and build the snapshot from it, falling back to `decision="unknown"` when absent.

**Tech Stack:** Python 3.12, pytest, LangChain/LangGraph middleware, Ansich contracts (`packages/ansich`), Ansich adapter (`packages/harness/deerflow/ansich`).

## Global Constraints

- Run all backend commands from `backend/`. Test command form: `PYTHONPATH=. uv run pytest <path> -v`.
- `packages/ansich/` (framework-independent core) must not import `deerflow`/`app`; the new contract lives in the **harness** package `packages/harness/deerflow/authz/`, which may import freely.
- Ruff line length 240, double quotes, space indent. Run `make format` before final commit.
- `AuthorizationSnapshot.policy_id` has `min_length=1`; `policy_hash` must match `^[0-9a-f]{64}$` (use `canonical_config_hash`).
- `AuthorizationOutcome.decision` is only ever `"allowed"` or `"denied"` (guardrail verdicts). `"unknown"` is produced solely by the Ansich fallback, never written by guardrail.
- `details_available=False` and `effective_permissions=()` in all cases for v1 (GuardrailDecision exposes no structured permissions).
- Context key value: `AUTHORIZATION_OUTCOME_CONTEXT_KEY = "__authorization_outcome"`.

---

### Task 1: Neutral `AuthorizationOutcome` contract

**Files:**
- Create: `backend/packages/harness/deerflow/authz/outcome.py`
- Test: `backend/tests/test_authorization_outcome.py`

**Interfaces:**
- Produces:
  - `AUTHORIZATION_OUTCOME_CONTEXT_KEY: str`
  - `@dataclass(frozen=True) AuthorizationOutcome(decision: Literal["allowed","denied"], policy_id: str, policy_version: str, reason_codes: tuple[str, ...] = (), details_available: bool = False, effective_permissions: tuple[str, ...] = ())`
  - `put_authorization_outcome(context: object, tool_call_id: object, outcome: AuthorizationOutcome) -> None`
  - `pop_authorization_outcome(context: object, tool_call_id: object) -> AuthorizationOutcome | None`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_authorization_outcome.py
from __future__ import annotations

from deerflow.authz.outcome import (
    AUTHORIZATION_OUTCOME_CONTEXT_KEY,
    AuthorizationOutcome,
    pop_authorization_outcome,
    put_authorization_outcome,
)


def _outcome(decision: str = "allowed") -> AuthorizationOutcome:
    return AuthorizationOutcome(decision=decision, policy_id="p", policy_version="1", reason_codes=("c",))


def test_put_then_pop_round_trips_and_consumes_entry() -> None:
    context: dict = {}
    put_authorization_outcome(context, "call-1", _outcome("denied"))
    popped = pop_authorization_outcome(context, "call-1")
    assert popped is not None and popped.decision == "denied"
    # pop-on-read consumes the entry
    assert pop_authorization_outcome(context, "call-1") is None


def test_pop_missing_key_returns_none() -> None:
    assert pop_authorization_outcome({}, "absent") is None
    assert pop_authorization_outcome({AUTHORIZATION_OUTCOME_CONTEXT_KEY: {}}, "absent") is None


def test_non_dict_context_and_falsy_id_are_no_ops() -> None:
    put_authorization_outcome(None, "call-1", _outcome())  # must not raise
    put_authorization_outcome({}, None, _outcome())  # falsy id -> no-op
    assert pop_authorization_outcome(None, "call-1") is None
    assert pop_authorization_outcome({}, None) is None


def test_parallel_ids_are_isolated() -> None:
    context: dict = {}
    put_authorization_outcome(context, "a", _outcome("allowed"))
    put_authorization_outcome(context, "b", _outcome("denied"))
    assert pop_authorization_outcome(context, "a").decision == "allowed"
    assert pop_authorization_outcome(context, "b").decision == "denied"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_authorization_outcome.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'deerflow.authz.outcome'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/packages/harness/deerflow/authz/outcome.py
"""Neutral Guardrail->observer authorization outcome contract.

GuardrailMiddleware writes an AuthorizationOutcome into the per-run runtime
context; the Ansich adapter pops it to stamp the real policy decision onto its
AuthorizationSnapshot. Neither side imports the other -- both depend only on
this contract. The context key is ``__``-prefixed so Gateway build_run_config
strips any caller-supplied forgery, matching ``__run_journal`` /
``__active_skill_secrets``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

AUTHORIZATION_OUTCOME_CONTEXT_KEY = "__authorization_outcome"


@dataclass(frozen=True)
class AuthorizationOutcome:
    decision: Literal["allowed", "denied"]
    policy_id: str
    policy_version: str
    reason_codes: tuple[str, ...] = ()
    details_available: bool = False
    effective_permissions: tuple[str, ...] = field(default_factory=tuple)


def put_authorization_outcome(context: object, tool_call_id: object, outcome: AuthorizationOutcome) -> None:
    if not isinstance(context, dict) or not tool_call_id:
        return
    store = context.get(AUTHORIZATION_OUTCOME_CONTEXT_KEY)
    if not isinstance(store, dict):
        store = {}
        context[AUTHORIZATION_OUTCOME_CONTEXT_KEY] = store
    store[tool_call_id] = outcome


def pop_authorization_outcome(context: object, tool_call_id: object) -> AuthorizationOutcome | None:
    if not isinstance(context, dict) or not tool_call_id:
        return None
    store = context.get(AUTHORIZATION_OUTCOME_CONTEXT_KEY)
    if not isinstance(store, dict):
        return None
    return store.pop(tool_call_id, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_authorization_outcome.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/authz/outcome.py backend/tests/test_authorization_outcome.py
git commit -m "feat(authz): add neutral AuthorizationOutcome context contract (H1)"
```

---

### Task 2: GuardrailMiddleware writes the outcome

**Files:**
- Modify: `backend/packages/harness/deerflow/guardrails/middleware.py`
- Test: `backend/tests/test_guardrail_middleware.py` (append)

**Interfaces:**
- Consumes: `AuthorizationOutcome`, `put_authorization_outcome`, `AUTHORIZATION_OUTCOME_CONTEXT_KEY` (Task 1).
- Produces: outcome entries in `context["__authorization_outcome"][tool_call_id]` on all allow/deny/error branches of `wrap_tool_call` / `awrap_tool_call`; a private `_build_authorization_outcome(self, decision: GuardrailDecision) -> AuthorizationOutcome`.

- [ ] **Step 1: Write the failing tests**

```python
# Append to backend/tests/test_guardrail_middleware.py
from deerflow.authz.outcome import pop_authorization_outcome  # add near top imports


class TestGuardrailWritesAuthorizationOutcome:
    def test_allow_writes_allowed_outcome_with_policy_identity(self):
        mw = GuardrailMiddleware(_AllowAllProvider())
        ctx: dict = {}
        req = _make_tool_call_request(context=ctx, call_id="c1")
        mw.wrap_tool_call(req, MagicMock())
        outcome = pop_authorization_outcome(ctx, "c1")
        assert outcome is not None
        assert outcome.decision == "allowed"
        assert outcome.reason_codes == ("oap.allowed",)
        assert outcome.policy_id  # non-empty resolved identity
        assert outcome.details_available is False
        assert outcome.effective_permissions == ()

    def test_deny_writes_denied_outcome_with_real_policy_id(self):
        mw = GuardrailMiddleware(_DenyAllProvider())
        ctx: dict = {}
        req = _make_tool_call_request(context=ctx, call_id="c2")
        mw.wrap_tool_call(req, MagicMock())
        outcome = pop_authorization_outcome(ctx, "c2")
        assert outcome is not None
        assert outcome.decision == "denied"
        assert outcome.policy_id == "test.deny.v1"
        assert "oap.denied" in outcome.reason_codes

    def test_fail_closed_provider_error_writes_denied_outcome(self):
        mw = GuardrailMiddleware(_ExplodingProvider(), fail_closed=True)
        ctx: dict = {}
        req = _make_tool_call_request(context=ctx, call_id="c3")
        mw.wrap_tool_call(req, MagicMock())
        outcome = pop_authorization_outcome(ctx, "c3")
        assert outcome is not None and outcome.decision == "denied"
        assert "oap.evaluator_error" in outcome.reason_codes

    def test_async_allow_writes_allowed_outcome(self):
        mw = GuardrailMiddleware(_AllowAllProvider())
        ctx: dict = {}
        req = _make_tool_call_request(context=ctx, call_id="c4")

        async def handler(_req):
            return MagicMock()

        asyncio.run(mw.awrap_tool_call(req, handler))
        outcome = pop_authorization_outcome(ctx, "c4")
        assert outcome is not None and outcome.decision == "allowed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_guardrail_middleware.py::TestGuardrailWritesAuthorizationOutcome -v`
Expected: FAIL — outcome is `None` (guardrail does not write yet)

- [ ] **Step 3: Implement the write side**

Add imports near the existing `from deerflow.guardrails.provider import ...` line in `middleware.py`:

```python
from deerflow.authz.outcome import AuthorizationOutcome, put_authorization_outcome
```

Add this helper method to `GuardrailMiddleware` (e.g. right after `_build_denied_message`):

```python
    def _build_authorization_outcome(self, decision: GuardrailDecision) -> AuthorizationOutcome:
        params = self.release_policy_parameters()
        policy = params.get("policy", {}) if isinstance(params, dict) else {}
        policy_id = decision.policy_id or str(policy.get("id") or "unknown")
        policy_version = str(policy.get("version") or "unknown")
        reason_codes = tuple(reason.code for reason in decision.reasons if reason.code)
        return AuthorizationOutcome(
            decision="allowed" if decision.allow else "denied",
            policy_id=policy_id,
            policy_version=policy_version,
            reason_codes=reason_codes,
            details_available=False,
            effective_permissions=(),
        )
```

In `wrap_tool_call`, write the outcome at the three decision-final points. In the
sync `except Exception:` block, add the `put_authorization_outcome(...)` line
immediately before each return:

```python
        except Exception:
            logger.exception("Guardrail provider error (sync)")
            if self.fail_closed:
                decision = GuardrailDecision(allow=False, reasons=[GuardrailReason(code="oap.evaluator_error", message="guardrail provider error (fail-closed)")])
                self._record_guardrail_event(context, gr, decision, action="deny_tool_call", provider_error=True)
                put_authorization_outcome(context, request.tool_call.get("id"), self._build_authorization_outcome(decision))
                return self._build_denied_message(request, decision)
            else:
                decision = GuardrailDecision(allow=True, reasons=[GuardrailReason(code="oap.evaluator_error", message="guardrail provider error (fail-open)")])
                self._record_guardrail_event(context, gr, decision, action="allow_tool_call_after_provider_error", provider_error=True)
                put_authorization_outcome(context, request.tool_call.get("id"), self._build_authorization_outcome(decision))
                return handler(request)
```

Then, immediately after the `try/except` block (before `if not decision.allow:`),
add one line that covers both the normal allow and normal deny paths:

```python
        put_authorization_outcome(context, request.tool_call.get("id"), self._build_authorization_outcome(decision))
        if not decision.allow:
            ...
```

Apply the identical three edits to `awrap_tool_call` (async `except` block's two
returns + the single line after the `try/except`, before `if not decision.allow:`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_guardrail_middleware.py -v`
Expected: PASS (all existing tests + 4 new)

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/guardrails/middleware.py backend/tests/test_guardrail_middleware.py
git commit -m "feat(guardrails): publish AuthorizationOutcome to runtime context (H1)"
```

---

### Task 3: Ansich reads the outcome; `unknown` fallback

**Files:**
- Modify: `backend/packages/harness/deerflow/ansich/tool_middleware.py`
  - `_record_authorization` (199-256), `_record_started` (168-196), `AnsichVisibleToolMiddleware.wrap_tool_call` (~636-642), `AnsichVisibleToolMiddleware.awrap_tool_call` (~681-687), `AnsichRawToolMiddleware.wrap_tool_call` (~715), `AnsichRawToolMiddleware.awrap_tool_call` (~757)
- Modify: `backend/tests/ansich/test_execution_context.py:307,362` (flip expected `authorization.allowed` -> `authorization.unknown`)
- Test: `backend/tests/ansich/test_execution_context.py` (append new cases)

**Interfaces:**
- Consumes: `AuthorizationOutcome`, `pop_authorization_outcome` (Task 1); outcome entries written by Task 2.
- Produces: `_record_authorization(execution, invocation, *, outcome: AuthorizationOutcome | None, fallback_reason_code: str)`; `_record_started(execution, invocation, *, authorization_outcome: AuthorizationOutcome | None = None)`.

- [ ] **Step 1: Update the two existing assertions (intentional semantic change)**

In `backend/tests/ansich/test_execution_context.py`, change the expected list
element `"authorization.allowed"` to `"authorization.unknown"` at **line 307**
(`test_sync_raw_probe_classifies_timeout...`) and **line 362**
(`test_async_raw_probe_classifies_cooperative_cancellation...`). These paths run
with no guardrail, so the snapshot decision is now `unknown`.

- [ ] **Step 2: Write the failing new tests**

```python
# Append to backend/tests/ansich/test_execution_context.py
from deerflow.authz.outcome import AuthorizationOutcome, put_authorization_outcome  # add to imports


def _snapshot_from_observations(observations):
    for item in observations:
        if item.kind.startswith("authorization."):
            return item.payload["snapshot"]
    raise AssertionError("no authorization snapshot recorded")


def test_raw_probe_records_unknown_when_no_guardrail_outcome(monkeypatch) -> None:
    execution = AnsichExecutionContext(task_id=new_id(), service=MagicMock())
    registration = execution.register_tool_call(
        tool_call_id=new_id(), step_id=new_id(), step_seq=1, call_seq=1,
        provider_call_id="prov-1", tool_name="write_file", args_hash="a" * 64, issued_obs_id=new_id(),
    )
    request = SimpleNamespace(
        runtime=SimpleNamespace(context={ANSICH_EXECUTION_CONTEXT_KEY: execution}),
        tool_call={"id": "prov-1", "name": "write_file", "args": {}},
    )
    observations: list = []
    monkeypatch.setattr(tool_observer, "_record_batch", lambda e, b, *, batch_kind: observations.extend(b) or True)
    with execution.activate_tool_invocation(registration):
        AnsichRawToolMiddleware().wrap_tool_call(request, lambda r: ToolMessage(content="ok", tool_call_id="prov-1", name="write_file"))
    snapshot = _snapshot_from_observations(observations)
    assert snapshot["decision"] == "unknown"
    assert snapshot["details_available"] is False


def test_raw_probe_records_real_allowed_from_guardrail_outcome(monkeypatch) -> None:
    execution = AnsichExecutionContext(task_id=new_id(), service=MagicMock())
    registration = execution.register_tool_call(
        tool_call_id=new_id(), step_id=new_id(), step_seq=1, call_seq=1,
        provider_call_id="prov-2", tool_name="bash", args_hash="a" * 64, issued_obs_id=new_id(),
    )
    context = {ANSICH_EXECUTION_CONTEXT_KEY: execution}
    put_authorization_outcome(context, "prov-2", AuthorizationOutcome(decision="allowed", policy_id="pol.x", policy_version="7", reason_codes=("oap.allowed",)))
    request = SimpleNamespace(runtime=SimpleNamespace(context=context), tool_call={"id": "prov-2", "name": "bash", "args": {}})
    observations: list = []
    monkeypatch.setattr(tool_observer, "_record_batch", lambda e, b, *, batch_kind: observations.extend(b) or True)
    with execution.activate_tool_invocation(registration):
        AnsichRawToolMiddleware().wrap_tool_call(request, lambda r: ToolMessage(content="ok", tool_call_id="prov-2", name="bash"))
    snapshot = _snapshot_from_observations(observations)
    assert snapshot["decision"] == "allowed"
    assert snapshot["policy_id"] == "pol.x"
    assert snapshot["policy_version"] == "7"
    assert "oap.allowed" in snapshot["reason_codes"]


def test_visible_probe_records_real_denied_on_short_circuit(monkeypatch) -> None:
    execution = AnsichExecutionContext(task_id=new_id(), service=MagicMock())
    registration = execution.register_tool_call(
        tool_call_id=new_id(), step_id=new_id(), step_seq=1, call_seq=1,
        provider_call_id="prov-3", tool_name="bash", args_hash="a" * 64, issued_obs_id=new_id(),
    )
    context = {ANSICH_EXECUTION_CONTEXT_KEY: execution}
    put_authorization_outcome(context, "prov-3", AuthorizationOutcome(decision="denied", policy_id="pol.deny", policy_version="2", reason_codes=("oap.denied",)))
    request = SimpleNamespace(runtime=SimpleNamespace(context=context), tool_call={"id": "prov-3", "name": "bash", "args": {}})
    observations: list = []
    monkeypatch.setattr(tool_observer, "_record_batch", lambda e, b, *, batch_kind: observations.extend(b) or True)
    # visible probe wraps a handler that short-circuits (never reaches raw probe -> not started)
    with execution.activate_tool_invocation(registration):
        AnsichVisibleToolMiddleware().wrap_tool_call(request, lambda r: ToolMessage(content="blocked", tool_call_id="prov-3", name="bash", status="error"))
    snapshot = _snapshot_from_observations(observations)
    assert snapshot["decision"] == "denied"
    assert snapshot["policy_id"] == "pol.deny"


def test_visible_probe_records_allowed_when_guardrail_allowed_but_downstream_blocked(monkeypatch) -> None:
    # Guardrail allowed (outcome present) but a non-authz gate blocked before raw probe.
    execution = AnsichExecutionContext(task_id=new_id(), service=MagicMock())
    registration = execution.register_tool_call(
        tool_call_id=new_id(), step_id=new_id(), step_seq=1, call_seq=1,
        provider_call_id="prov-4", tool_name="write_file", args_hash="a" * 64, issued_obs_id=new_id(),
    )
    context = {ANSICH_EXECUTION_CONTEXT_KEY: execution}
    put_authorization_outcome(context, "prov-4", AuthorizationOutcome(decision="allowed", policy_id="pol.allow", policy_version="1", reason_codes=("oap.allowed",)))
    request = SimpleNamespace(runtime=SimpleNamespace(context=context), tool_call={"id": "prov-4", "name": "write_file", "args": {}})
    observations: list = []
    monkeypatch.setattr(tool_observer, "_record_batch", lambda e, b, *, batch_kind: observations.extend(b) or True)
    with execution.activate_tool_invocation(registration):
        AnsichVisibleToolMiddleware().wrap_tool_call(request, lambda r: ToolMessage(content="blocked by read-before-write", tool_call_id="prov-4", name="write_file", status="error"))
    snapshot = _snapshot_from_observations(observations)
    assert snapshot["decision"] == "allowed"  # NOT denied
    assert snapshot["policy_id"] == "pol.allow"
```

- [ ] **Step 3: Run new tests to verify they fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ansich/test_execution_context.py -k "guardrail_outcome or unknown_when_no_guardrail or real_denied_on_short_circuit or downstream_blocked" -v`
Expected: FAIL — signature/behavior not implemented (snapshots still `allowed`/`denied` synthetic).

- [ ] **Step 4: Implement the read side**

Add import near the top of `tool_middleware.py` (with the other `deerflow` imports):

```python
from deerflow.authz.outcome import AuthorizationOutcome, pop_authorization_outcome
```

Add a tiny context helper (near `_known_secrets`):

```python
def _runtime_context(request: ToolCallRequest) -> object:
    return getattr(getattr(request, "runtime", None), "context", None)
```

Replace `_record_authorization`'s signature and identity-resolution head. Change:

```python
def _record_authorization(
    execution: AnsichExecutionContext,
    invocation: ToolInvocation,
    *,
    decision: str,
    reason_code: str,
) -> None:
    if invocation.authorization_recorded:
        return
    registration = invocation.registration
    snapshot_id = new_id()
    ...
    snapshot = AuthorizationSnapshot(
        snapshot_id=snapshot_id,
        tool_call_id=registration.tool_call_id,
        policy_id="deerflow-tool-middleware-chain",
        policy_version="1",
        policy_hash=canonical_config_hash({"policy": "deerflow-tool-middleware-chain", "version": "1"}),
        decision=decision,
        details_available=False,
        reason_codes=(reason_code,),
        evaluated_at=evaluated_at,
        evidence_obs_ids=(evaluated_obs_id, decision_obs_id),
    )
```

to:

```python
def _record_authorization(
    execution: AnsichExecutionContext,
    invocation: ToolInvocation,
    *,
    outcome: AuthorizationOutcome | None,
    fallback_reason_code: str,
) -> None:
    if invocation.authorization_recorded:
        return
    registration = invocation.registration
    if outcome is not None:
        decision = outcome.decision
        policy_id = outcome.policy_id
        policy_version = outcome.policy_version
        reason_codes = outcome.reason_codes or (fallback_reason_code,)
        details_available = outcome.details_available
    else:
        # No authorization layer evaluated this call: record it honestly as
        # unknown. The evidence code still says whether the callable was
        # reached, but the decision no longer masquerades as an authz verdict.
        decision = "unknown"
        policy_id = "deerflow-tool-middleware-chain"
        policy_version = "1"
        reason_codes = (fallback_reason_code,)
        details_available = False
    snapshot_id = new_id()
    evaluated_obs_id = new_id()
    decision_obs_id = new_id()
    evaluated_at = datetime.now(UTC)
    snapshot = AuthorizationSnapshot(
        snapshot_id=snapshot_id,
        tool_call_id=registration.tool_call_id,
        policy_id=policy_id,
        policy_version=policy_version,
        policy_hash=canonical_config_hash({"policy": policy_id, "version": policy_version}),
        decision=decision,
        details_available=details_available,
        reason_codes=reason_codes,
        evaluated_at=evaluated_at,
        evidence_obs_ids=(evaluated_obs_id, decision_obs_id),
    )
```

(The rest of `_record_authorization` — the `common` dict, `evaluated`/`decided`
observation envelopes using `f"authorization.{decision}"`, `_record_batch`, and
`invocation.authorization_recorded = True` — is unchanged.)

Update `_record_started` to accept and forward the outcome:

```python
def _record_started(
    execution: AnsichExecutionContext,
    invocation: ToolInvocation,
    *,
    authorization_outcome: AuthorizationOutcome | None = None,
) -> None:
    registration = invocation.registration
    invocation.started = True
    invocation.started_at = time.monotonic()
    _record_authorization(
        execution,
        invocation,
        outcome=authorization_outcome,
        fallback_reason_code="callable_boundary_entered",
    )
    ...  # (observation build + _record_batch unchanged)
```

In `AnsichRawToolMiddleware.wrap_tool_call`, replace the `_record_started(execution, invocation)` call (~line 715):

```python
            outcome = pop_authorization_outcome(_runtime_context(request), request.tool_call.get("id"))
            _record_started(execution, invocation, authorization_outcome=outcome)
```

Apply the identical change in `AnsichRawToolMiddleware.awrap_tool_call` (~line 757).

In `AnsichVisibleToolMiddleware.wrap_tool_call` (~636-642), replace the denied
`_record_authorization` call:

```python
                    if not invocation.started:
                        outcome = pop_authorization_outcome(_runtime_context(request), request.tool_call.get("id"))
                        _record_authorization(
                            execution,
                            invocation,
                            outcome=outcome,
                            fallback_reason_code="short_circuited_before_callable",
                        )
```

Apply the identical change in `AnsichVisibleToolMiddleware.awrap_tool_call` (~681-687).

- [ ] **Step 5: Run the full Ansich execution-context suite**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ansich/test_execution_context.py -v`
Expected: PASS (existing updated assertions + 4 new tests)

- [ ] **Step 6: Commit**

```bash
git add backend/packages/harness/deerflow/ansich/tool_middleware.py backend/tests/ansich/test_execution_context.py
git commit -m "feat(ansich): bridge real guardrail decision into AuthorizationSnapshot; unknown fallback (H1)"
```

---

### Task 4: scope-safety guard — no false `policy_denial`

**Files:**
- Test: `backend/tests/ansich/test_scope_safety_assessment.py` (append)

**Interfaces:**
- Consumes: the existing `_snapshot(...)` helper and `assess_scope_safety` already used in this test module.

- [ ] **Step 1: Write the test**

```python
# Append to backend/tests/ansich/test_scope_safety_assessment.py

def test_unknown_decision_does_not_produce_policy_denial() -> None:
    result = assess_scope_safety(
        tool_call_id="tc-unknown",
        task_scopes=(),
        authorization_snapshots=(_snapshot(decision="unknown"),),
        intended_effects=(),
        observed_effects=(),
    )
    assert result.conclusions["policy_denial"].value is False


def test_allowed_but_blocked_call_does_not_produce_policy_denial() -> None:
    # A guardrail-allowed call blocked downstream still records decision="allowed";
    # scope-safety must not read that as a policy denial.
    result = assess_scope_safety(
        tool_call_id="tc-allowed",
        task_scopes=(),
        authorization_snapshots=(_snapshot(decision="allowed"),),
        intended_effects=(),
        observed_effects=(),
    )
    assert result.conclusions["policy_denial"].value is False
```

Note: match `assess_scope_safety`'s actual call signature and the conclusion
accessor already used elsewhere in this file (inspect an existing test in the
module first; adapt `_snapshot(...)` arguments and the `conclusions[...]` access
to the real API if they differ).

- [ ] **Step 2: Run to verify it passes** (the domain logic already treats unknown/allowed as non-denial; this pins it)

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ansich/test_scope_safety_assessment.py -k "policy_denial" -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/ansich/test_scope_safety_assessment.py
git commit -m "test(ansich): pin unknown/allowed decisions produce no policy_denial (H1)"
```

---

### Task 5: Docs + full-suite verification

**Files:**
- Modify: `ansich/docs/plans/phase-9-review-followups.md` (H1 overview row + H1 status line + test-matrix gap bullet)
- Modify: `backend/AGENTS.md` (Ansich section — one line)

- [ ] **Step 1: Update the followup doc**

In `ansich/docs/plans/phase-9-review-followups.md`:
- Overview table row H1: change status cell `⬜ 未修复` → `✅ 已修复`, fill 修复时间 `2026-07-21` and the H1 fix commit hash.
- H1 section `- 状态:` line → `✅ 已修复`, appending a one-line note: bridged real Guardrail decision via the neutral `deerflow.authz.outcome` context contract; `decision="unknown"` recorded when no authorization layer evaluated the call; `details_available=false` retained (GuardrailDecision exposes no structured permissions).
- Test-matrix gap section: strike/annotate the H1 bullet as covered by `test_authorization_outcome.py` + the new `test_execution_context.py` cases (unknown now exercised on a production path).

- [ ] **Step 2: Update backend/AGENTS.md**

In the Ansich Phase-3 tool-probe paragraph (the one describing intent/raw/visible
probes and authorization), add one sentence:

> The authorization snapshot bridges the real `GuardrailMiddleware` decision
> (policy id/version/decision/reason codes) through the neutral
> `deerflow.authz.outcome` context contract; when no authorization layer
> evaluated the call it records `decision="unknown"` with
> `details_available=false` rather than a synthetic allow/deny.

- [ ] **Step 3: Format + full targeted verification**

```bash
cd backend && make format
PYTHONPATH=. uv run pytest tests/test_authorization_outcome.py tests/test_guardrail_middleware.py tests/ansich/test_execution_context.py tests/ansich/test_scope_safety_assessment.py tests/ansich/test_safety_contracts.py tests/ansich/test_sql_safety.py -v
```
Expected: PASS (no regressions in the manually-constructed safety/SQL snapshot tests, which are unaffected).

- [ ] **Step 4: Commit**

```bash
git add ansich/docs/plans/phase-9-review-followups.md backend/AGENTS.md
git commit -m "docs(ansich): mark H1 fixed; document authorization snapshot bridge"
```

---

## Self-Review

**Spec coverage:**
- Neutral contract (`deerflow.authz.outcome`) → Task 1. ✓
- Guardrail write side, 4×2 branches + helper → Task 2. ✓
- Ansich read side, `_record_authorization` refactor + 2 raw + 2 visible sites, unknown fallback → Task 3. ✓
- Semantic model (allowed/denied real, unknown fallback; allowed-but-blocked → allowed) → Task 3 tests 2/4. ✓
- No-regression: existing `authorization.allowed` middleware assertions intentionally flipped to `unknown` → Task 3 Step 1. ✓
- scope_safety no false `policy_denial` → Task 4. ✓
- details_available=false / effective_permissions=() v1 → enforced in Task 1 defaults + Task 2 helper. ✓
- Docs (followup doc + AGENTS.md) → Task 5. ✓
- Named tools (`write_file`/`bash`) not only `timeout_tool` → Task 3 tests use `write_file`/`bash`. ✓

**Placeholder scan:** Task 4 Step 1 carries a deliberate "inspect the real API first" note because the exact `assess_scope_safety` signature / conclusion accessor must match the existing module — this is guidance to verify against real code, not a code placeholder. All code steps contain complete code.

**Type consistency:** `AuthorizationOutcome` fields, `put/pop_authorization_outcome` signatures, `_record_authorization(outcome=, fallback_reason_code=)`, and `_record_started(authorization_outcome=)` are consistent across Tasks 1–3.
