"""exact_match grader — extract a value from the trace, compare to expected.

Path syntax is intentionally narrow:
  - `final_text`                            → trace.final_text
  - `stop_reason`                           → trace.stop_reason
  - `tool_calls[N]`                         → the Nth ToolCall dict
  - `tool_calls[N].result`                  → that call's result
  - `tool_calls[N].result.<key>[.<key>...]` → dotted descent into a dict/list
  - `tool_calls[N].input.<key>`             → dotted descent into input

`[N]` indexes work on lists; non-negative integers only.

Negative or computed indices would invite surprises in graders that
read like configuration; if you need them, write a structural grader.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from .base import GradeResult, GraderConfigError

if TYPE_CHECKING:
    from ..case import TestCase
    from ..trace import Trace


_INDEX_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\]$")


class ExactMatchGrader:
    type = "exact_match"

    def __init__(self, config: dict[str, Any]) -> None:
        if "path" not in config:
            raise GraderConfigError("exact_match grader requires 'path'")
        if "expected" not in config:
            raise GraderConfigError("exact_match grader requires 'expected'")
        self._path: str = config["path"]
        self._expected: Any = config["expected"]
        # Validate the path now so a typo fails at suite-load, not run-time.
        _validate_path(self._path)

    def grade(self, case: "TestCase", trace: "Trace") -> GradeResult:
        try:
            actual = _resolve_path(trace, self._path)
        except (KeyError, IndexError, AttributeError) as e:
            return GradeResult(
                grader_type=self.type,
                passed=False,
                score=0.0,
                notes=f"path {self._path!r} did not resolve: {e}",
                metadata={"path": self._path, "expected": self._expected, "actual": None},
            )
        passed = actual == self._expected
        return GradeResult(
            grader_type=self.type,
            passed=passed,
            score=1.0 if passed else 0.0,
            notes=(
                f"{self._path} == {self._expected!r}"
                if passed
                else f"{self._path} = {actual!r}, expected {self._expected!r}"
            ),
            metadata={"path": self._path, "expected": self._expected, "actual": actual},
        )


# ---------------------------------------------------------------------------
# Path resolution.
# ---------------------------------------------------------------------------

def _validate_path(path: str) -> None:
    for segment in path.split("."):
        if not segment:
            raise GraderConfigError(f"path {path!r}: empty segment")
        if _INDEX_RE.fullmatch(segment):
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", segment):
            raise GraderConfigError(f"path {path!r}: invalid segment {segment!r}")


def _resolve_path(trace: "Trace", path: str) -> Any:
    segments = path.split(".")
    head = segments[0]
    rest = segments[1:]

    # Root segment can be a top-level Trace field, optionally indexed.
    idx_match = _INDEX_RE.fullmatch(head)
    if idx_match:
        field_name, idx = idx_match.group(1), int(idx_match.group(2))
        seq = _trace_field(trace, field_name)
        value: Any = _coerce_dataclass(seq[idx])
    else:
        value = _trace_field(trace, head)

    for segment in rest:
        m = _INDEX_RE.fullmatch(segment)
        if m:
            key, idx = m.group(1), int(m.group(2))
            value = _coerce_dataclass(value)
            value = value[key][idx] if isinstance(value, dict) else getattr(value, key)[idx]
        else:
            value = _coerce_dataclass(value)
            if isinstance(value, dict):
                value = value[segment]
            else:
                value = getattr(value, segment)
    return value


def _trace_field(trace: "Trace", name: str) -> Any:
    if not hasattr(trace, name):
        raise KeyError(f"Trace has no field {name!r}")
    return getattr(trace, name)


def _coerce_dataclass(value: Any) -> Any:
    """If value is a dataclass instance (ToolCall, Turn), expose it as a dict
    so dotted descent into `.input`, `.result`, `.name` works uniformly."""
    from dataclasses import is_dataclass

    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value
