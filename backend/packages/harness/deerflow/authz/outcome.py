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
