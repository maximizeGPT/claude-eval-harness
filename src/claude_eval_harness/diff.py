"""Compute case-level deltas between two runs.

Cases align by id. Classification:
  regressed  — passed in A, failed in B
  fixed      — failed in A, passed in B
  changed    — same passed/failed status, but grader metadata drifted
               (covers the llm_judge case where the reasoning shifted)
  unchanged  — same status, identical grader metadata

`compute_deltas` returns a flat list ordered: regressed, fixed, changed, unchanged.
The reporter consumes this directly.
"""

from __future__ import annotations

from typing import Any

from . import SCHEMA_VERSION
from .storage import CaseResult, RunRecord


class DiffError(RuntimeError):
    """Raised when two runs can't be meaningfully compared."""


def compute_deltas(a: RunRecord, b: RunRecord) -> list[dict[str, Any]]:
    if _major(a.schema_version) != _major(b.schema_version):
        raise DiffError(
            f"refusing to diff across schema majors: a={a.schema_version}, b={b.schema_version}. "
            f"Re-run the older run against the current harness, or use `harness show` "
            f"on each separately."
        )
    if a.schema_version != SCHEMA_VERSION or b.schema_version != SCHEMA_VERSION:
        # Same major, different minor — allowed, but worth flagging in metadata.
        pass

    a_by_id = {c.id: c for c in a.cases}
    b_by_id = {c.id: c for c in b.cases}
    all_ids = list(dict.fromkeys([*a_by_id.keys(), *b_by_id.keys()]))

    deltas: list[dict[str, Any]] = []
    for cid in all_ids:
        ca = a_by_id.get(cid)
        cb = b_by_id.get(cid)
        if ca is None:
            deltas.append({"case_id": cid, "kind": "added", "details": [f"new in {b.run_id}"]})
            continue
        if cb is None:
            deltas.append({"case_id": cid, "kind": "removed", "details": [f"present in {a.run_id}, missing in {b.run_id}"]})
            continue
        deltas.append(_compare_case(ca, cb))

    # Stable sort: known kinds first, then everything else by id.
    order = {"regressed": 0, "fixed": 1, "changed": 2, "added": 3, "removed": 4, "unchanged": 5}
    deltas.sort(key=lambda d: (order.get(str(d["kind"]), 99), str(d["case_id"])))
    return deltas


def _compare_case(a: CaseResult, b: CaseResult) -> dict[str, Any]:
    if a.status == "passed" and b.status != "passed":
        return {
            "case_id": a.id,
            "kind": "regressed",
            "details": _grader_diff_lines(a, b),
        }
    if a.status != "passed" and b.status == "passed":
        return {
            "case_id": a.id,
            "kind": "fixed",
            "details": _grader_diff_lines(a, b),
        }
    # Same status — check whether grader metadata drifted.
    drift = _grader_diff_lines(a, b)
    if drift:
        return {"case_id": a.id, "kind": "changed", "details": drift}
    return {"case_id": a.id, "kind": "unchanged", "details": []}


def _grader_diff_lines(a: CaseResult, b: CaseResult) -> list[str]:
    out: list[str] = []
    a_by_type = {g.grader_type: g for g in a.graders}
    b_by_type = {g.grader_type: g for g in b.graders}
    for gtype in dict.fromkeys([*a_by_type, *b_by_type]):
        ga = a_by_type.get(gtype)
        gb = b_by_type.get(gtype)
        if ga is None:
            out.append(f"{gtype}: added (now {'PASS' if gb and gb.passed else 'FAIL'})")
            continue
        if gb is None:
            out.append(f"{gtype}: removed (was {'PASS' if ga.passed else 'FAIL'})")
            continue
        if ga.passed != gb.passed:
            out.append(f"{gtype}: {_pf(ga.passed)} -> {_pf(gb.passed)} ({gb.notes})")
        elif ga.metadata != gb.metadata:
            out.append(f"{gtype}: metadata drift while {_pf(ga.passed)}")
            for k in sorted(set(ga.metadata) | set(gb.metadata)):
                va, vb = ga.metadata.get(k), gb.metadata.get(k)
                if va != vb:
                    out.append(f"  - {k}: {va!r} -> {vb!r}")
    return out


def _pf(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def _major(version: int) -> int:
    return version
