# H1: Bridge real Guardrail decisions into Ansich AuthorizationSnapshot

- **Date**: 2026-07-21
- **Source**: `ansich/docs/plans/phase-9-review-followups.md` item **H1**
- **Branch**: `ansich-dev`
- **Status**: design approved, ready for plan

## Problem

`AuthorizationSnapshot` is the audit evidence Ansich persists to describe how a tool
call was authorized. Today its `policy_id` / `policy_version` / `policy_hash` are
hardcoded constants and its `decision` is inferred from a single binary signal —
"did execution reach the real callable boundary?" — recorded at two call sites in
`tool_middleware.py::_record_authorization`:

- `_record_started` (via `AnsichRawToolMiddleware`) records `decision="allowed"`,
  `reason_code="callable_boundary_entered"`.
- `AnsichVisibleToolMiddleware.wrap_tool_call`, on `not invocation.started`, records
  `decision="denied"`, `reason_code="short_circuited_before_callable"`.

Two defects follow:

1. **Synthetic policy identity.** The real authorization layer is
   `GuardrailMiddleware` (chain slot #9, active when `guardrails.enabled`). Its
   `GuardrailDecision` carries the actual `policy_id`, `reasons[].code`, and
   allow/deny verdict, but Ansich never reads it — there is no import of guardrails
   under `deerflow.ansich`, and Guardrail only writes to `__run_journal`, a parallel
   path. So the persisted `policy_id="deerflow-tool-middleware-chain"` is unrelated
   to whatever policy actually decided the call.

2. **Wrong attribution of short-circuits.** `not invocation.started` is **not**
   guardrail-specific. In the tail chain (outer→inner):
   `... Guardrail → SandboxAudit → ReadBeforeWrite → ToolProgress →
   ToolErrorHandling → AnsichRaw`, both **ReadBeforeWrite** blocks
   (`read_before_write_middleware.py:110/143`) and **ToolProgress BLOCKED** short
   circuit *after* Guardrail already allowed the call but *before* AnsichRaw runs.
   They are currently recorded as `decision="denied"` with a fake policy — and
   because `scope_safety.py` computes `policy_denial = bool(decision=="denied")`,
   a mere "file not read yet" block produces a **false `policy_denial` safety
   conclusion**.

`decision="unknown"` is supported by the contract (`safety.py:29`) and handled
correctly by `scope_safety.assess_scope_safety` (unknown ≠ violation), but it is
never constructed on any production path.

## Design decisions (approved)

1. **Semantic boundary — record the real authorization verdict.** When Guardrail
   evaluated the call, the snapshot reflects *its* decision, independent of whether a
   downstream non-authorization gate later blocked execution. Only a genuine
   Guardrail deny yields `decision="denied"`.
2. **Contract ownership — neutral module `deerflow.authz`.** Guardrail writes, the
   Ansich adapter reads; neither imports the other. Both depend on a small neutral
   contract (Guardrail already imports `deerflow.authz.principal`).
3. **No authorization layer ⇒ `decision="unknown"`.** When guardrails are disabled,
   or Guardrail did not evaluate this tool, the snapshot records `decision="unknown"`
   with `details_available=false`. The snapshot reflects *authorization only*;
   whether the tool executed or was blocked is captured separately by
   `started`/effects/visible-result. This finally exercises `unknown` on a production
   path and eliminates false `policy_denial`.

## Model

`AuthorizationSnapshot` reflects the authorization layer's verdict, nothing else.

| Scenario | `decision` | policy identity | `reason_codes` | `details_available` |
| --- | --- | --- | --- | --- |
| Guardrail evaluated → allow | `allowed` | real (`decision.policy_id` + provider version) | real guardrail reason codes | `false` (v1) |
| Guardrail evaluated → deny | `denied` | real | real | `false` |
| No authorization outcome (guardrails off / not evaluated) | `unknown` | neutral sentinel | execution-evidence code¹ | `false` |

¹ With no authorization outcome, `callable_boundary_entered` /
`short_circuited_before_callable` are retained as **execution evidence** reason
codes, but `decision` is `unknown` — the code describes whether the callable was
reached, and no longer masquerades as an authorization verdict.

**Key correctness win:** when Guardrail allows but ReadBeforeWrite/ToolProgress
blocks, Ansich reads `outcome=allowed` and records `allowed` (not `denied`), so no
false `policy_denial` is produced.

## Components & data flow

### New neutral contract — `packages/harness/deerflow/authz/outcome.py`

- `@dataclass AuthorizationOutcome` with fields: `decision: Literal["allowed",
  "denied"]`, `policy_id: str`, `policy_version: str`, `reason_codes:
  tuple[str, ...]`, `details_available: bool` (v1 always `False`),
  `effective_permissions: tuple[...] = ()` (v1 always empty).
- `AUTHORIZATION_OUTCOME_CONTEXT_KEY = "__authorization_outcome"` — `__`-prefixed so
  Gateway `build_run_config` strips any caller-supplied forgery, matching
  `__run_journal` / `__active_skill_secrets`.
- `put_authorization_outcome(context, tool_call_id, outcome)` — writes into the
  per-run `context[KEY]` dict, no-op when `context` is not a dict.
- `pop_authorization_outcome(context, tool_call_id) -> AuthorizationOutcome | None`
  — pop-on-read so entries do not accumulate and a single call is consumed once.

### Write side — `guardrails/middleware.py`

In `wrap_tool_call` and `awrap_tool_call`, in **all four** decision branches
(allow, deny, provider-error fail-closed, provider-error fail-open), build an
`AuthorizationOutcome` from the computed `GuardrailDecision` and write it into
`context` under `request.tool_call["id"]` **before** returning the denied message or
calling `handler(request)`. A helper `_build_authorization_outcome(decision)`
resolves:

- `decision` string = `"denied"` if `not decision.allow` else `"allowed"`
- `policy_id` = `decision.policy_id` or the middleware's resolved provider policy id
  (from `release_policy_parameters()["policy"]["id"]`)
- `policy_version` = resolved provider policy version
  (`release_policy_parameters()["policy"]["version"]`)
- `reason_codes` = `tuple(r.code for r in decision.reasons if r.code)`
- `details_available=False`, `effective_permissions=()` (v1)

### Read side — `ansich/tool_middleware.py`

`_record_authorization` stops taking hardcoded `decision` / `reason_code`. Instead
each call site resolves an outcome via `pop_authorization_outcome(context,
request.tool_call["id"])` (the same `ToolCallRequest` flows through the chain, so the
provider tool-call id is identical for Guardrail and Ansich; the snapshot is still
stored under Ansich's authoritative `registration.tool_call_id`):

- **AnsichRaw `_record_started`** (callable reached): outcome present → real
  `allowed`; outcome absent → `unknown` (evidence code `callable_boundary_entered`).
- **AnsichVisible `not started`** (short-circuited): outcome present → use
  `outcome.decision` (may be `denied`, or `allowed` when a non-authz gate blocked);
  outcome absent → `unknown` (evidence code `short_circuited_before_callable`).

The `unknown` fallback keeps the existing sentinel `policy_id
="deerflow-tool-middleware-chain"` / `policy_version="1"` (non-empty as required by
the contract); the real signal is carried by `decision="unknown"` +
`details_available=false`. No new constant, to preserve historical comparability.

The `invocation.authorization_recorded` idempotency guard is unchanged, so exactly
one snapshot is recorded per call.

## Scope / non-goals (v1)

- `GuardrailDecision` exposes no structured permission set, so `details_available`
  stays `false` and `effective_permissions` stays empty in every case — per plan §3
  ("provider returns bool only ⇒ details_available=false, do not guess
  permissions"). Structured permissions are an extension point for the real authz
  adapter (RFC `docs/plans/2026-07-10-pluggable-authorization-rfc.md`).
- The pop-on-read entry may linger when Ansich is disabled but Guardrail writes;
  bounded by tool-calls-per-run in ephemeral per-run `context`, discarded with the
  run. Acceptable.

## Testing (TDD, `backend/tests/`)

1. **`outcome.py` unit** — put/pop round-trip, missing key → `None`, non-dict
   context → no-op.
2. **Guardrail real deny** — stub provider denies with `policy_id="X"`, reason code
   `"Y"`; assert persisted snapshot `decision="denied"`, `policy_id="X"`,
   `reason_codes` contains `"Y"`.
3. **Guardrails disabled → unknown** — assert snapshot `decision="unknown"`,
   `details_available=false`. (First production-path exercise of `unknown`; closes
   the H1 test-matrix gap.)
4. **Option A correctness** — Guardrail allows + ReadBeforeWrite blocks → snapshot
   `decision="allowed"` (not `denied`).
5. **scope_safety integration** — `unknown` and `allowed`-but-blocked produce **no**
   `policy_denial` conclusion.
6. Named tools (`write_file` / `bash`), not only `timeout_tool`.

## Files touched

- **new** `packages/harness/deerflow/authz/outcome.py`
- `packages/harness/deerflow/guardrails/middleware.py` — write outcome in 4×2
  branches + `_build_authorization_outcome` helper
- `packages/harness/deerflow/ansich/tool_middleware.py` — `_record_authorization`
  and its two call sites read outcome; `unknown` fallback
- **new** test file(s) under `backend/tests/`
- `ansich/docs/plans/phase-9-review-followups.md` — mark H1 ✅ 已修复 (overview table
  + H1 status line + test-matrix gap)
- `backend/AGENTS.md` — one line in the Ansich section noting the snapshot now
  bridges the real Guardrail decision and records `unknown` when no authz layer ran
