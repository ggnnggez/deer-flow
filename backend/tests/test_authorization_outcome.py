"""Tests for the neutral AuthorizationOutcome context contract (H1)."""

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
