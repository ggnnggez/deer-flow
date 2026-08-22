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

* ``0`` -- the pass settled and reported nothing.
* ``1`` -- the pass ran and something is still owed (unsettled work, durably
  failed jobs, or no digest). Re-running is the remedy; the store is fine.
* ``2`` -- the request itself was refused (a target this build cannot honour, a
  malformed filter, or no SQL store configured). Re-running changes nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime

from ansich import ReplayReport, ReplaySelector
from ansich.errors import ReplayTargetError
from pydantic import ValidationError

from deerflow.ansich.persistence.sql import SqlAnsichBackend
from deerflow.ansich.replay import DEFAULT_MAX_ROUNDS, execute_replay, plan_replay
from deerflow.config import get_app_config
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config

__all__ = ["build_parser", "exit_code", "main", "selector_from_args"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m deerflow.ansich.replay_cli",
        description="Re-derive one Ansich projector's read models over a slice of Observation history.",
    )
    parser.add_argument("--projector", required=True, help="Projector name to replay, e.g. task-step")
    parser.add_argument("--version", required=True, help="Projector version this build should run")
    parser.add_argument("--task-id", help="Restrict the target set to one Task")
    parser.add_argument("--occurred-from", help="ISO-8601 start of an occurred_at window (naive values are read as UTC)")
    parser.add_argument("--occurred-to", help="ISO-8601 end of an occurred_at window")
    parser.add_argument("--ingest-from", type=int, help="Lowest ingest_seq to target")
    parser.add_argument("--ingest-to", type=int, help="Highest ingest_seq to target")
    parser.add_argument("--dry-run", action="store_true", help="Report what the replay would do and write nothing")
    parser.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS, help="Bounded drain-then-recount rounds before reporting what is still owed")
    parser.add_argument("--format", choices=["json", "text"], default="json")
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
    """``0`` for a clean pass, ``1`` for one that has something to report."""

    if report.dry_run:
        return 0
    return 1 if report.unsettled or report.digest is None else 0


def render(report: ReplayReport, *, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report.model_dump(), indent=2, sort_keys=True)
    lines = [
        f"target:    {report.projector_name}@{report.projector_version}{' (dry run)' if report.dry_run else ''}",
        f"targeted:  {report.targeted} ({report.minted} minted, {report.re_pended} re-pended)",
        f"replayed:  {report.replayed} (store-wide, not target-scoped)",
        f"unsettled: {report.unsettled}",
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
            **kwargs,
        )
    finally:
        await close_engine()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        selector = selector_from_args(args)
    except (ValidationError, ValueError) as error:
        print(f"invalid replay filter: {error}", file=sys.stderr)
        return 2
    try:
        report = asyncio.run(run(args, selector))
    except ReplayTargetError as error:
        print(f"replay refused ({error.reason}): {error}", file=sys.stderr)
        return 2
    except RuntimeError as error:
        print(f"replay unavailable: {error}", file=sys.stderr)
        return 2
    print(render(report, output_format=args.format))
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
