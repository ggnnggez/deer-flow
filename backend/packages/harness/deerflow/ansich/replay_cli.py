"""CLI entry point for versioned Ansich replay.

A thin argument parser over :mod:`deerflow.ansich.replay` -- every decision
worth making lives in that module, and this file's only jobs are turning
strings into a :class:`~ansich.contracts.ReplaySelector`, opening the store the
running Gateway would open, and turning a report into an exit code.

Run it as ``python -m deerflow.ansich.replay_cli --projector NAME --version V``.

It is a command rather than a route on purpose (spec §5): a replay re-pends
durable jobs and clears read models under a cross-worker lock, which is an
operator action taken deliberately from a shell, not something a request should
be able to trigger. That is also why it lives harness-side and imports no
``app.*``.

**Exit codes are the machine-readable half of the report**, because a script
that has to parse prose to decide whether to page someone will get it wrong:

* ``0`` -- the pass settled and nothing is owed.
* ``1`` -- the pass ran and work is still owed: jobs still unsettled, or jobs
  durably failed for this target. Re-running (or an operator retry) is the
  remedy; the request was fine. A **missing digest is not** one of these
  conditions on its own -- three projectors own no read-model table
  exclusively and honestly have none.
* ``2`` -- the request itself was refused (a target this build cannot honour, a
  malformed filter, a ``--replace`` this build will not honour, or no SQL store
  configured). Re-running changes nothing.

**A missing digest now has a fourth reason, and it is not a failure either**
(batch-final finding B2): ``expired`` counts targeted Observations whose payload
retention has already removed. Their jobs settle without deriving anything, so
the read model this pass produced cannot be compared with one derived before the
sweep -- the digest is refused rather than reported, and the count says why. The
exit code is deliberately unchanged by it: nothing is owed and re-running would
not bring the bytes back. ``--replace`` over such a target set is **refused**
(``replace_over_expired_evidence``, exit ``2``), because there the owned tables
are emptied before the re-derive and the missing rows do not come back.

``--replace`` is the destructive flag and reads as one: it empties the target
projector's own read-model tables and re-derives them, so the report's digest
describes rows this history actually produces rather than rows that merely
survived. It is whole-table (plan ruling RC4) -- combining it with a filter is
refused rather than approximated -- and it is available only for projectors
whose ability to restore what it deletes is proven by a test
(``_REPLACE_PROVEN_PROJECTORS``); everything else is refused with
``replace_restore_unproven`` and the remedy named in the message.

**One target is known-broken even without ``--replace``.** A *plain* replay of
``task-control`` on a store whose control Observations have already been
projected collides on ``ansich_transitions.evidence_obs_id`` and walks those
jobs to durable failure (see ``_NON_IDEMPOTENT_PROJECTORS``). Exit code ``1``
alone would read as a transient backlog and send the operator back into the
same collision, so the defect is named on stderr before the pass and again
beside a non-clean report. It is a warning rather than a refusal because the
same command is correct on a store where those Observations have never been
projected.

**Two subcommands stand beside the replay**, and they are here rather than on a
route for the same reason the replay is (spec §5): they are deliberate operator
actions from a shell, not something a request should trigger.

* ``activate --component-kind K --component-name N --version V --actor WHO`` is
  the **only** writer of ``ansich_active_versions``. It refuses an unknown
  kind, name or version before writing anything, and writes the selection row
  and its audit Observation in one transaction — spec §5's "explicit,
  audited management action" is that pairing, not the row alone. Exit ``0`` on
  success, ``2`` on refusal or an unavailable store.
* ``versions`` lists, read-only, every versioned component this build knows:
  what is active now (a row, or the code default when there is none), the code
  default, and the versions this build can execute.

An absent row means the code default, so ``activate`` records *deviations* and
an empty table is a complete answer rather than a missing one.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime

from ansich import ActiveVersion, ReplayReport, ReplaySelector
from ansich.errors import ActiveVersionError, ReplayTargetError
from pydantic import ValidationError

from deerflow.ansich.persistence.sql import (
    _NON_IDEMPOTENT_PROJECTORS,
    ACTIVE_VERSION_COMPONENT_KINDS,
    SqlAnsichBackend,
    _active_version_registry,
    active_version_caveat,
)
from deerflow.ansich.replay import DEFAULT_MAX_ROUNDS, execute_replay, plan_replay
from deerflow.config import get_app_config
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config

__all__ = [
    "build_parser",
    "exit_code",
    "main",
    "render_versions",
    "selector_from_args",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m deerflow.ansich.replay_cli",
        description="Re-derive one Ansich projector's read models over a slice of Observation history.",
    )
    # `--projector`/`--version` are **not** `required=True` even though a
    # replay needs both. Subcommands share this parser, and argparse enforces a
    # top-level required option before it ever reaches the subparser, so
    # `activate ...` would be refused for missing `--projector`. The
    # requirement is therefore checked in `main` for the replay path only,
    # which keeps `python -m ... --projector X --version 1` working exactly as
    # before and lets the subcommands stand beside it.
    parser.add_argument("--projector", help="Projector name to replay, e.g. task-step")
    parser.add_argument("--version", help="Projector version this build should run")
    parser.add_argument("--task-id", help="Restrict the target set to one Task")
    parser.add_argument("--occurred-from", help="ISO-8601 start of an occurred_at window (naive values are read as UTC)")
    parser.add_argument("--occurred-to", help="ISO-8601 end of an occurred_at window")
    parser.add_argument("--ingest-from", type=int, help="Lowest ingest_seq to target")
    parser.add_argument("--ingest-to", type=int, help="Highest ingest_seq to target")
    parser.add_argument("--dry-run", action="store_true", help="Report what the replay would do and write nothing")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete the projector's own read-model tables whole before re-deriving them. Whole-table only: refused with any filter, and refused for a projector whose restore is not proven.",
    )
    parser.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS, help="Bounded drain-then-recount rounds before reporting what is still owed")
    parser.add_argument("--format", choices=["json", "text"], default="json")

    subcommands = parser.add_subparsers(dest="command")
    activate = subcommands.add_parser(
        "activate",
        help="Record which version of one versioned component is authoritative, and audit the switch.",
        description=(
            "Switch a versioned component's active version. This is the ONLY writer of the active-version row: "
            "the row and its audit Observation are written in one transaction, so a switch is never unaccounted for. "
            "An absent row means the code default, so this command records deviations from it."
        ),
    )
    activate.add_argument("--component-kind", required=True, choices=list(ACTIVE_VERSION_COMPONENT_KINDS), help="Which family of versioned component to switch")
    activate.add_argument("--component-name", required=True, help="The component's name, e.g. task-step or ansich-default")
    activate.add_argument("--version", required=True, help="The version to make authoritative; refused unless this build knows it")
    activate.add_argument("--actor", required=True, help="Who is taking this action; recorded on the row and in the audit Observation")
    activate.add_argument("--format", choices=["json", "text"], default="json")

    versions = subcommands.add_parser(
        "versions",
        help="List what is active now, what the code default is, and which versions this build can execute.",
        description=("Read-only. Lists every versioned component this build knows: the version currently active (a stored row, or the code default when there is none), the code default itself, and the executable set."),
    )
    versions.add_argument("--format", choices=["json", "text"], default="json")
    return parser


def _parse_timestamp(value: str) -> datetime:
    """ISO-8601 in, aware UTC out.

    A naive value is read as UTC rather than passed through. Comparing a naive
    bound against ``occurred_at`` -- a timezone-aware column -- raises on
    PostgreSQL and silently compares text on SQLite, so "assume the operator's
    local zone" and "leave it naive" are both worse than saying UTC here and in
    the ``--help``.
    """

    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def selector_from_args(args: argparse.Namespace) -> ReplaySelector:
    """Build the selector, letting its own validators refuse a bad window.

    Half-given ranges and reversed ones are rejected by
    :class:`~ansich.contracts.ReplaySelector` rather than by argparse, so the
    CLI and any programmatic caller refuse the same shapes for the same
    reasons.
    """

    return ReplaySelector(
        task_id=args.task_id,
        occurred_from=None if args.occurred_from is None else _parse_timestamp(args.occurred_from),
        occurred_to=None if args.occurred_to is None else _parse_timestamp(args.occurred_to),
        ingest_from=args.ingest_from,
        ingest_to=args.ingest_to,
    )


def exit_code(report: ReplayReport) -> int:
    """``0`` for a clean pass, ``1`` for one that left work owed.

    Two facts decide it, and both have to be here because neither implies the
    other. ``unsettled`` counts ``pending``/``retry``/``processing`` and
    excludes ``failed`` — a durably failed job is *settled*, badly — so a pass
    can end with ``unsettled == 0``, a computable digest, and N projections
    that will never land. Reading only ``unsettled`` is what let that pass exit
    ``0`` while its own ``errors`` said otherwise (review finding F2), which is
    exactly the prose-parsing this exit code exists to spare a script.

    A missing digest is deliberately **not** part of the test. Three projectors
    own no read-model table exclusively and honestly have no digest (see
    ``_PROJECTOR_OWNED_TABLES``); paging on that would make a clean replay of
    ``task-structural`` look like an incident and train an operator to ignore
    the code. When a digest is missing *because* work is owed, the two counts
    below already say so. ``expired_evidence`` is the same shape and stays out
    for the same reason plus one of its own: a pass over evidence retention
    removed owes nothing and cannot be re-run into a different answer, so exit
    ``1`` would name a remedy that does not exist. It is reported in the counts
    and in ``errors``, and the destructive case is refused at ``2`` instead.

    A dry run always exits ``0``: it reports, it changes nothing, and a plan
    that found a backlog is a successful plan.
    """

    if report.dry_run:
        return 0
    return 1 if report.unsettled or report.failed else 0


def known_defect_warning(projector_name: str) -> str | None:
    """The stderr line for a target whose re-projection is known to fail.

    Printed **before** the pass runs, because the operator's decision is
    whether to run it at all -- and printed again beside a non-clean report,
    because exit code ``1`` says "work is owed" and reads as a transient
    backlog. For a known-non-idempotent target it is not transient: re-running
    and ``retry_failed_projections`` both re-collide, so an operator following
    the ordinary remedy loops forever on a defect nothing in the report names.

    Not a refusal (see ``_NON_IDEMPOTENT_PROJECTORS``): the same command is
    correct on a store whose target Observations have never been projected.
    """

    mechanism = _NON_IDEMPOTENT_PROJECTORS.get(projector_name)
    if mechanism is None:
        return None
    return f"warning: {projector_name} has a known projector-idempotence defect: {mechanism}"


def render(report: ReplayReport, *, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report.model_dump(), indent=2, sort_keys=True)
    lines = [
        f"target:    {report.projector_name}@{report.projector_version}{' (dry run)' if report.dry_run else ''}",
        f"targeted:  {report.targeted} ({report.minted} minted, {report.re_pended} re-pended)",
        f"replayed:  {report.replayed} (store-wide, not target-scoped)",
        f"unsettled: {report.unsettled}",
        f"failed:    {report.failed}",
        f"expired:   {report.expired_evidence} (targeted Observation(s) whose payload retention removed)",
        f"watermark: {'unknown' if report.watermark is None else report.watermark}",
        f"digest:    {report.digest or '(none)'}",
    ]
    lines.extend(f"note:      {error}" for error in report.errors)
    return "\n".join(lines)


async def run(args: argparse.Namespace, selector: ReplaySelector) -> ReplayReport:
    """Open the store the Gateway would open, run the pass, close it again.

    No ``AnsichService`` is started: starting one would run a projector loop
    and an operations tick beside the replay's own drive loop, so two
    projectors in one process would contend over the same claims for no
    benefit. The backend is what a replay needs.
    """

    config = get_app_config()
    await init_engine_from_config(config.database)
    try:
        session_factory = get_session_factory()
        if session_factory is None:
            raise RuntimeError("Ansich replay needs a SQL database; `database.backend: memory` stores no Observations to replay")
        backend = SqlAnsichBackend(session_factory)
        replay = plan_replay if args.dry_run else execute_replay
        kwargs = {} if args.dry_run else {"max_rounds": args.max_rounds}
        return await replay(
            backend,
            projector_name=args.projector,
            projector_version=args.version,
            selector=selector,
            replace=args.replace,
            **kwargs,
        )
    finally:
        await close_engine()


def render_versions(active: tuple[ActiveVersion, ...], *, output_format: str) -> str:
    """The ``versions`` listing: what runs, what would run, what could run.

    Three columns rather than one because they answer three different
    questions, and an operator about to switch something needs all three: the
    active version (with where it came from), the code default that a row's
    absence would fall back to, and the executable set an ``activate`` would be
    checked against. A row whose ``origin`` is ``code_default`` is marked as
    such rather than being rendered identically to a row that deliberately
    activated the same version.
    """

    registry = _active_version_registry()
    rows = [
        {
            "component_kind": entry.component_kind,
            "component_name": entry.component_name,
            "active_version": entry.active_version,
            "code_default_version": entry.code_default_version,
            "origin": entry.origin,
            "activated_at": None if entry.activated_at is None else entry.activated_at.isoformat(),
            "activated_by": entry.activated_by,
            "audit_obs_id": entry.audit_obs_id,
            "known_versions": list(registry[(entry.component_kind, entry.component_name)][0]),
            # Per *known* version, not only the active one: this listing is what
            # an operator reads while deciding what to switch to, so a caveat
            # that only appeared after the switch would be told too late.
            "version_caveats": {version: caveat for version in registry[(entry.component_kind, entry.component_name)][0] if (caveat := active_version_caveat(entry.component_kind, entry.component_name, version)) is not None},
        }
        for entry in active
    ]
    if output_format == "json":
        return json.dumps({"components": rows}, indent=2, sort_keys=True)
    lines = []
    for row in rows:
        marker = " (code default)" if row["origin"] == "code_default" else f" ({row['origin']}, by {row['activated_by']})"
        lines.append(f"{row['component_kind']}/{row['component_name']}: {row['active_version']}{marker}")
        lines.append(f"    code default: {row['code_default_version']}    known: {', '.join(row['known_versions'])}")
        for version, caveat in sorted(row["version_caveats"].items()):
            lines.append(f"    caveat ({version}): {caveat}")
    return "\n".join(lines)


async def run_activate(args: argparse.Namespace) -> ActiveVersion:
    """Open the store, write the switch and its audit together, close it again."""

    config = get_app_config()
    await init_engine_from_config(config.database)
    try:
        session_factory = get_session_factory()
        if session_factory is None:
            raise RuntimeError("Ansich version activation needs a SQL database; `database.backend: memory` stores no active-version row")
        backend = SqlAnsichBackend(session_factory)
        return await backend.activate_version(
            component_kind=args.component_kind,
            component_name=args.component_name,
            version=args.version,
            actor=args.actor,
        )
    finally:
        await close_engine()


async def run_versions(_args: argparse.Namespace) -> tuple[ActiveVersion, ...]:
    """Read the current selection, code defaults included."""

    config = get_app_config()
    await init_engine_from_config(config.database)
    try:
        session_factory = get_session_factory()
        if session_factory is None:
            raise RuntimeError("Ansich version listing needs a SQL database; `database.backend: memory` stores no active-version row")
        return await SqlAnsichBackend(session_factory).get_active_versions()
    finally:
        await close_engine()


def _main_activate(args: argparse.Namespace) -> int:
    caveat = active_version_caveat(args.component_kind, args.component_name, args.version)
    if caveat is not None:
        # Before the write, because the operator's decision is whether to make
        # it at all — the same placement, and the same reasoning, as the
        # known-defect warning on the replay path.
        print(f"warning: {caveat}", file=sys.stderr)
    try:
        activated = asyncio.run(run_activate(args))
    except ActiveVersionError as error:
        print(f"activation refused ({error.reason}): {error}", file=sys.stderr)
        return 2
    except ValueError as error:
        # `ActiveVersionError` is itself a `ValueError`, and `except` on the
        # subclass does not catch the parent — so without this clause any other
        # refusal shaped as a bad argument (a validator on the envelope, say)
        # escaped as a traceback and exited `1`, the code this CLI publishes as
        # "the pass ran and work is owed; re-run me". A refusal must exit `2`.
        print(f"activation refused: {error}", file=sys.stderr)
        return 2
    except RuntimeError as error:
        print(f"activation unavailable: {error}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(activated.model_dump(mode="json"), indent=2, sort_keys=True))
    else:
        print(f"activated:  {activated.component_kind}/{activated.component_name} -> {activated.active_version}")
        print(f"code default: {activated.code_default_version}")
        print(f"origin:     {activated.origin}")
        print(f"audit:      {activated.audit_obs_id or '(none)'}")
    return 0


def _main_versions(args: argparse.Namespace) -> int:
    try:
        active = asyncio.run(run_versions(args))
    except RuntimeError as error:
        print(f"version listing unavailable: {error}", file=sys.stderr)
        return 2
    print(render_versions(active, output_format=args.format))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = getattr(args, "command", None)
    if command == "activate":
        return _main_activate(args)
    if command == "versions":
        return _main_versions(args)
    # The replay path. Its two arguments are checked here rather than through
    # `required=True` so the subcommands above can be reached at all; see
    # `build_parser`.
    if not args.projector or not args.version:
        print("replay needs --projector and --version (or use a subcommand: activate, versions)", file=sys.stderr)
        return 2
    try:
        selector = selector_from_args(args)
    except (ValidationError, ValueError) as error:
        print(f"invalid replay filter: {error}", file=sys.stderr)
        return 2
    defect = known_defect_warning(args.projector)
    if defect is not None:
        print(defect, file=sys.stderr)
    try:
        report = asyncio.run(run(args, selector))
    except ReplayTargetError as error:
        print(f"replay refused ({error.reason}): {error}", file=sys.stderr)
        return 2
    except RuntimeError as error:
        print(f"replay unavailable: {error}", file=sys.stderr)
        return 2
    print(render(report, output_format=args.format))
    code = exit_code(report)
    if code and defect is not None:
        # Attribution, not decoration: without it the failure reads as a
        # backlog and the operator retries into the same collision.
        print(f"note: this pass left work owed and {args.projector} carries the defect above; re-running will not clear it", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
