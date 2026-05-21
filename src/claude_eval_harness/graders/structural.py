"""structural grader — all-of requirements over the tool-call sequence.

Each requirement matches against one tool call in the trace. By default,
a requirement matches if any tool call in the trace satisfies it; pin
to a specific position with `index: N`.

Requirement keys (all optional except `tool`):
  tool:             string — tool name must equal this
  index:            int    — match only the Nth tool call (0-indexed)
  args:             dict   — every key must be present in the call's input
                             with a value satisfying the matcher (see below)
  result:           dict   — every key must be present in the call's result
                             with a value satisfying the matcher
  result_ok:        bool   — call's result_ok must equal this
  result_contains:  string — substring of JSON-encoded result

Matcher syntax for args/result values:
  - scalar (str/int/float/bool)    → exact equality
  - {">=": n} / {">": n} / {"<=": n} / {"<": n} / {"==": v} / {"!=": v}
  - {"between": [lo, hi]}          → lo <= v <= hi
  - list                           → deep equality with nested matchers

Failed requirements are reported individually so the user sees which
predicate broke, not just that the grader failed.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .base import GradeResult, GraderConfigError

if TYPE_CHECKING:
    from ..case import TestCase
    from ..trace import Trace


_COMPARATORS = {">=", ">", "<=", "<", "==", "!="}


class StructuralGrader:
    type = "structural"

    def __init__(self, config: dict[str, Any]) -> None:
        require = config.get("require")
        if not isinstance(require, list) or not require:
            raise GraderConfigError("structural grader requires a non-empty 'require' list")
        for i, req in enumerate(require):
            if not isinstance(req, dict):
                raise GraderConfigError(
                    f"structural grader: require[{i}] must be a mapping, got {type(req).__name__}"
                )
            if "tool" not in req:
                raise GraderConfigError(f"structural grader: require[{i}] missing 'tool'")
        self._require: list[dict[str, Any]] = require

    def grade(self, case: "TestCase", trace: "Trace") -> GradeResult:
        results: list[dict[str, Any]] = []
        for i, req in enumerate(self._require):
            ok, reason = _match_requirement(req, trace)
            results.append({"index": i, "ok": ok, "tool": req.get("tool"), "reason": reason})

        all_ok = all(r["ok"] for r in results)
        if all_ok:
            notes = f"all {len(results)} requirement(s) met"
        else:
            failed = [r for r in results if not r["ok"]]
            notes = "; ".join(f"req[{r['index']}] {r['tool']}: {r['reason']}" for r in failed)

        return GradeResult(
            grader_type=self.type,
            passed=all_ok,
            score=1.0 if all_ok else 0.0,
            notes=notes,
            metadata={"requirements": results},
        )


# ---------------------------------------------------------------------------
# Requirement matching.
# ---------------------------------------------------------------------------

def _match_requirement(req: dict[str, Any], trace: "Trace") -> tuple[bool, str]:
    tool_name = req["tool"]
    index = req.get("index")

    candidates = trace.tool_calls
    if index is not None:
        if not isinstance(index, int) or index < 0 or index >= len(candidates):
            return False, f"index={index} out of range (trace has {len(candidates)} tool calls)"
        candidates = [candidates[index]]

    matched_any = False
    last_reason = ""
    for call in candidates:
        if call.name != tool_name:
            last_reason = f"name {call.name!r} != {tool_name!r}"
            continue
        ok, why = _check_call_against_req(call, req)
        if ok:
            matched_any = True
            break
        last_reason = why

    if matched_any:
        return True, "matched"
    if not candidates:
        return False, f"no tool calls in trace"
    return False, last_reason or f"no call to {tool_name!r} satisfied requirement"


def _check_call_against_req(call: Any, req: dict[str, Any]) -> tuple[bool, str]:
    if "result_ok" in req and call.result_ok != req["result_ok"]:
        return False, f"result_ok={call.result_ok!r}, expected {req['result_ok']!r}"

    if "args" in req:
        ok, why = _match_partial(call.input, req["args"], path="args")
        if not ok:
            return False, why

    if "result" in req:
        ok, why = _match_partial(call.result, req["result"], path="result")
        if not ok:
            return False, why

    if "result_contains" in req:
        needle = req["result_contains"]
        haystack = call.result if isinstance(call.result, str) else json.dumps(call.result, default=str)
        if needle not in haystack:
            return False, f"result does not contain {needle!r}"

    return True, "matched"


def _match_partial(actual: Any, expected: Any, *, path: str) -> tuple[bool, str]:
    """Recursively check that `expected` is a subset/match of `actual`.

    Dicts compare key-by-key, lists deep-equal, scalars equal, dicts with
    a comparator key apply the comparator. The `path` argument carries
    the dotted location into the failure message so a deep mismatch reads
    like 'result.total_matched: 12 >= 30 is false'.
    """
    if isinstance(expected, dict) and _is_comparator(expected):
        return _apply_comparator(actual, expected, path=path)
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False, f"{path}: expected dict, got {type(actual).__name__}"
        for k, v in expected.items():
            if k not in actual:
                return False, f"{path}.{k}: missing"
            ok, why = _match_partial(actual[k], v, path=f"{path}.{k}")
            if not ok:
                return False, why
        return True, "matched"
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False, f"{path}: expected list, got {type(actual).__name__}"
        if len(actual) != len(expected):
            return False, f"{path}: length {len(actual)} != expected {len(expected)}"
        for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
            ok, why = _match_partial(a, e, path=f"{path}[{i}]")
            if not ok:
                return False, why
        return True, "matched"
    if actual != expected:
        return False, f"{path}: {actual!r} != {expected!r}"
    return True, "matched"


def _is_comparator(d: dict[str, Any]) -> bool:
    if len(d) != 1:
        return False
    key = next(iter(d))
    return key in _COMPARATORS or key == "between"


def _apply_comparator(actual: Any, expected: dict[str, Any], *, path: str) -> tuple[bool, str]:
    op, value = next(iter(expected.items()))
    try:
        if op == ">=":
            return (actual >= value, f"{path}: {actual!r} >= {value!r}")
        if op == ">":
            return (actual > value, f"{path}: {actual!r} > {value!r}")
        if op == "<=":
            return (actual <= value, f"{path}: {actual!r} <= {value!r}")
        if op == "<":
            return (actual < value, f"{path}: {actual!r} < {value!r}")
        if op == "==":
            return (actual == value, f"{path}: {actual!r} == {value!r}")
        if op == "!=":
            return (actual != value, f"{path}: {actual!r} != {value!r}")
        if op == "between":
            lo, hi = value
            return (lo <= actual <= hi, f"{path}: {actual!r} in [{lo}, {hi}]")
    except TypeError as e:
        return False, f"{path}: comparator {op} failed: {e}"
    return False, f"{path}: unknown comparator {op}"
