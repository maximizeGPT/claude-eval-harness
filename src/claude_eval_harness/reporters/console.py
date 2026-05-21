"""Plain-text reporters for `run`, `show`, and `diff`.

No external dep — print() and string formatting only. Width-targeted to
80 cols so it reads cleanly piped to less or a CI log viewer.
"""

from __future__ import annotations

from typing import TextIO

from ..storage import CaseResult, RunRecord


def report_run(record: RunRecord, *, out: TextIO) -> None:
    print(f"run: {record.run_id}", file=out)
    print(f"suite: {record.suite_path}  model: {record.model}", file=out)
    print(f"started: {record.started_at}  ended: {record.ended_at}", file=out)
    print("", file=out)
    for case in record.cases:
        _print_case(case, out=out)
    _print_totals(record, out=out)


def report_case(case: CaseResult, *, out: TextIO, verbose: bool = True) -> None:
    """Full detail for one case — used by `harness show --case`."""
    _print_case(case, out=out, verbose=verbose)


def _print_case(case: CaseResult, *, out: TextIO, verbose: bool = False) -> None:
    badge = _status_badge(case.status)
    duration = f"{case.duration_ms} ms"
    cost = _case_cost_str(case)
    print(f"{badge}  {case.id}  ({duration}{cost})", file=out)
    if case.error:
        print(f"    error: {case.error}", file=out)
    for g in case.graders:
        mark = "ok" if g.passed else "FAIL"
        print(f"    [{mark}] {g.grader_type}: {g.notes}", file=out)
    if verbose and case.trace is not None:
        print("", file=out)
        print(f"    prompt: {case.trace.prompt.strip()}", file=out)
        for i, tc in enumerate(case.trace.tool_calls):
            ok = "ok" if tc.result_ok else "ERR"
            print(f"    tool[{i}] {tc.name}({_compact_dict(tc.input)}) -> [{ok}] ({tc.duration_ms} ms)", file=out)
            print(f"        result: {_truncate(_compact_dict(tc.result), 200)}", file=out)
        if case.trace.final_text:
            print(f"    final_text: {_truncate(case.trace.final_text, 400)}", file=out)
    print("", file=out)


def _print_totals(record: RunRecord, *, out: TextIO) -> None:
    t = record.totals
    print("-" * 60, file=out)
    print(
        f"totals: {t['passed']}/{t['cases']} passed, {t['failed']} failed, {t['errored']} errored",
        file=out,
    )
    total_cost = sum((c.trace.usage.cost_usd if c.trace else 0.0) for c in record.cases)
    total_judge = sum((c.trace.usage.judge_cost_usd if c.trace else 0.0) for c in record.cases)
    total_in = sum((c.trace.usage.input_tokens if c.trace else 0) for c in record.cases)
    total_out = sum((c.trace.usage.output_tokens if c.trace else 0) for c in record.cases)
    total_ms = sum(c.duration_ms for c in record.cases)
    judge_suffix = f" (+${total_judge:.4f} judge)" if total_judge > 0 else ""
    print(
        f"usage:  input={total_in:,} tok  output={total_out:,} tok  "
        f"cost=${total_cost:.4f}{judge_suffix}  wall={total_ms} ms",
        file=out,
    )


# ---------------------------------------------------------------------------
# diff reporter — flagged changes go here.
# ---------------------------------------------------------------------------

def report_diff(deltas: list[dict[str, object]], *, out: TextIO) -> None:
    """Pretty-print the output of diff.compute_deltas.

    Order: regressed first (loudest signal), then fixed, then changed
    (same pass/fail but grader metadata drifted — important for llm_judge
    runs where the reasoning shifted), then unchanged tallied at the end.
    """
    sections: dict[str, list[dict[str, object]]] = {
        "regressed": [d for d in deltas if d["kind"] == "regressed"],
        "fixed":     [d for d in deltas if d["kind"] == "fixed"],
        "changed":   [d for d in deltas if d["kind"] == "changed"],
    }
    unchanged = sum(1 for d in deltas if d["kind"] == "unchanged")

    for label in ("regressed", "fixed", "changed"):
        items = sections[label]
        if not items:
            continue
        print(f"== {label} ({len(items)}) ==", file=out)
        for d in items:
            print(f"  {d['case_id']}", file=out)
            for line in d.get("details", []):
                print(f"    {line}", file=out)
        print("", file=out)
    print(f"unchanged: {unchanged}", file=out)


# ---------------------------------------------------------------------------
# Formatting helpers.
# ---------------------------------------------------------------------------

def _status_badge(status: str) -> str:
    return {"passed": "PASS", "failed": "FAIL", "errored": "ERR "}.get(status, status.upper())


def _case_cost_str(case: CaseResult) -> str:
    if case.trace is None:
        return ""
    u = case.trace.usage
    base = f", {u.input_tokens}+{u.output_tokens} tok, ${u.cost_usd:.4f}"
    if u.judge_cost_usd > 0:
        base += f" (+${u.judge_cost_usd:.4f} judge)"
    return base


def _compact_dict(value: object) -> str:
    import json

    try:
        return json.dumps(value, default=str, separators=(",", ":"))
    except TypeError:
        return repr(value)


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[: limit - 3] + "..."
