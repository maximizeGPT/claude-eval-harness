"""argparse entrypoint. Verbs: run, diff, show, list."""

from __future__ import annotations

import argparse
import fnmatch
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .case import Suite
from .client import HarnessClient, cost_usd
from .config import load_suite
from .diff import compute_deltas
from .graders import GradeResult, build_grader
from .reporters.console import report_case, report_diff, report_run
from .runner import run_case
from .storage import (
    CaseResult,
    make_record,
    new_run_id,
    read_run,
    trace_from_json,
    write_run,
)
from .target import get_target


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.verb:
        parser.print_help()
        return 2
    handler = {
        "run": _cmd_run,
        "diff": _cmd_diff,
        "show": _cmd_show,
        "list": _cmd_list,
    }[args.verb]
    return handler(args)


# ---------------------------------------------------------------------------
# Parser.
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="harness", description=__doc__)
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="verb")

    pr = sub.add_parser("run", help="Run a suite, write run JSON to disk")
    pr.add_argument("suite", help="Path to suite YAML")
    pr.add_argument("--model", help="Override the suite's default model")
    pr.add_argument("--filter", default=None, help="Glob pattern matched against case id")
    pr.add_argument("--out", default=None, help="Output JSON path (default: runs/<run_id>.json)")
    pr.add_argument("--max-turns", type=int, default=None, help="Override suite's max_turns")
    pr.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolved case list without calling the API",
    )

    pd = sub.add_parser("diff", help="Compare two runs")
    pd.add_argument("run_a", help="Path to baseline run JSON")
    pd.add_argument("run_b", help="Path to comparison run JSON")
    pd.add_argument("--only", default=None, help="Comma-separated kinds: regressed,fixed,changed,unchanged")

    ps = sub.add_parser("show", help="Print one run")
    ps.add_argument("run", help="Path to run JSON")
    ps.add_argument("--case", default=None, help="Show only this case id")

    pl = sub.add_parser("list", help="List runs in a directory")
    pl.add_argument("--dir", default="runs", help="Runs directory (default: runs)")
    pl.add_argument("--limit", type=int, default=20, help="Max rows to print")

    return p


# ---------------------------------------------------------------------------
# Verbs.
# ---------------------------------------------------------------------------

def _cmd_run(args: argparse.Namespace) -> int:
    suite, sha = load_suite(args.suite)
    cases = suite.cases
    if args.filter:
        cases = [c for c in cases if fnmatch.fnmatchcase(c.id, args.filter)]
        if not cases:
            print(f"no cases match filter {args.filter!r}", file=sys.stderr)
            return 1

    model = args.model or suite.model
    max_turns = args.max_turns or suite.max_turns
    fixtures_dir = _resolve_fixtures_dir(suite, args.suite)

    if args.dry_run:
        print(f"suite: {suite.name}  model: {model}  cases: {len(cases)}")
        for c in cases:
            graders = ",".join(g.type for g in c.graders)
            print(f"  - {c.id} [{graders}]")
        return 0

    target = get_target(suite.target, fixtures_dir=str(fixtures_dir))
    client = HarnessClient()
    suite_dir = Path(args.suite).resolve().parent

    started = _iso_utc()
    started_perf = time.monotonic()
    results: list[CaseResult] = []
    for case in cases:
        case_start = time.monotonic()
        try:
            if case.fixture_trace:
                trace = _load_fixture_trace(case.fixture_trace, suite_dir=suite_dir)
            else:
                trace = run_case(case, target=target, client=client, model=model, max_turns=max_turns)
            graders = [build_grader(spec).grade(case, trace) for spec in case.graders]
            trace.usage.judge_cost_usd = _judge_cost_from_graders(graders)
            status = "passed" if all(g.passed for g in graders) else "failed"
            results.append(
                CaseResult(
                    id=case.id,
                    status=status,
                    duration_ms=int((time.monotonic() - case_start) * 1000),
                    trace=trace,
                    graders=graders,
                )
            )
        except Exception as e:
            results.append(
                CaseResult(
                    id=case.id,
                    status="errored",
                    duration_ms=int((time.monotonic() - case_start) * 1000),
                    trace=None,
                    graders=[],
                    error=f"{type(e).__name__}: {e}",
                )
            )
    ended = _iso_utc()
    _wall = int((time.monotonic() - started_perf) * 1000)

    run_id = new_run_id(model)
    out_path = Path(args.out) if args.out else Path("runs") / f"{run_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    record = make_record(
        run_id=run_id,
        suite_path=str(args.suite),
        suite_sha256=sha,
        model=model,
        started_at=started,
        ended_at=ended,
        cases=results,
    )
    write_run(record, out_path)
    report_run(record, out=sys.stdout)
    print(f"wrote {out_path}", file=sys.stderr)
    return 0 if record.totals["failed"] == 0 and record.totals["errored"] == 0 else 1


def _cmd_diff(args: argparse.Namespace) -> int:
    a = read_run(args.run_a)
    b = read_run(args.run_b)
    deltas = compute_deltas(a, b)
    if args.only:
        keep = {k.strip() for k in args.only.split(",")}
        deltas = [d for d in deltas if d["kind"] in keep]
    report_diff(deltas, out=sys.stdout)
    has_regressions = any(d["kind"] == "regressed" for d in deltas)
    return 1 if has_regressions else 0


def _cmd_show(args: argparse.Namespace) -> int:
    record = read_run(args.run)
    if args.case is None:
        report_run(record, out=sys.stdout)
        return 0
    for case in record.cases:
        if case.id == args.case:
            report_case(case, out=sys.stdout, verbose=True)
            return 0
    print(f"no case named {args.case!r} in {args.run}", file=sys.stderr)
    return 1


def _cmd_list(args: argparse.Namespace) -> int:
    d = Path(args.dir)
    if not d.is_dir():
        print(f"no such directory: {d}", file=sys.stderr)
        return 1
    rows: list[tuple[str, str, str, int, int]] = []
    for p in sorted(d.glob("*.json")):
        try:
            r = read_run(p)
        except Exception as e:
            print(f"  ! {p.name}: unreadable ({e})", file=sys.stderr)
            continue
        rows.append((r.run_id, r.model, r.started_at, r.totals["passed"], r.totals["cases"]))
    rows = rows[-args.limit :] if args.limit else rows
    for run_id, model, started, passed, total in rows:
        print(f"{started}  {passed}/{total}  {model}  {run_id}")
    return 0


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------

def _iso_utc() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_fixture_trace(rel_path: str, *, suite_dir: Path):  # type: ignore[no-untyped-def]
    """Load a pre-built Trace from a JSON file on disk.

    Path is resolved relative to the suite YAML's directory so a suite
    can reference fixtures portably. The file's shape mirrors a single
    run's `case.trace` block — see storage.trace_from_json.
    """
    import json

    p = (suite_dir / rel_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"fixture_trace not found: {p}")
    return trace_from_json(json.loads(p.read_text()))


def _judge_cost_from_graders(graders: list[GradeResult]) -> float:
    """Sum dollar cost of every llm_judge call recorded in grader metadata."""
    total = 0.0
    for g in graders:
        if g.grader_type != "llm_judge":
            continue
        model = g.metadata.get("judge_model", "")
        in_tok = int(g.metadata.get("judge_input_tokens", 0) or 0)
        out_tok = int(g.metadata.get("judge_output_tokens", 0) or 0)
        total += cost_usd(model, in_tok, out_tok)
    return total


def _resolve_fixtures_dir(suite: Suite, suite_path: str) -> Path:
    raw = Path(suite.fixtures_dir)
    if raw.is_absolute():
        return raw
    return (Path(suite_path).parent / raw).resolve()


if __name__ == "__main__":
    raise SystemExit(main())
