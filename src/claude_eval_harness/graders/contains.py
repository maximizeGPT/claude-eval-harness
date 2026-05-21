"""contains grader — substring check against a trace field or tool result.

Resolves a path (same syntax as exact_match) to a string, then verifies
one of:
  - `any_of: [str, ...]`   — passes if ANY substring is found
  - `all_of: [str, ...]`   — passes if ALL substrings are found

Non-string targets are JSON-encoded first, so a result dict can be
searched for a value the same way as a final_text string.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .base import GradeResult, GraderConfigError
from .exact_match import _resolve_path, _validate_path

if TYPE_CHECKING:
    from ..case import TestCase
    from ..trace import Trace


class ContainsGrader:
    type = "contains"

    def __init__(self, config: dict[str, Any]) -> None:
        if "target" not in config:
            raise GraderConfigError("contains grader requires 'target' (path into trace)")
        if "any_of" not in config and "all_of" not in config:
            raise GraderConfigError("contains grader requires 'any_of' or 'all_of'")
        if "any_of" in config and "all_of" in config:
            raise GraderConfigError("contains grader: specify 'any_of' or 'all_of', not both")

        self._target_path: str = config["target"]
        _validate_path(self._target_path)

        if "any_of" in config:
            self._mode = "any_of"
            self._needles: list[str] = list(config["any_of"])
        else:
            self._mode = "all_of"
            self._needles = list(config["all_of"])
        if not self._needles:
            raise GraderConfigError(f"contains grader: '{self._mode}' must be non-empty")
        if not all(isinstance(n, str) for n in self._needles):
            raise GraderConfigError(f"contains grader: '{self._mode}' entries must be strings")

        self._case_sensitive: bool = bool(config.get("case_sensitive", False))

    def grade(self, case: "TestCase", trace: "Trace") -> GradeResult:
        try:
            raw = _resolve_path(trace, self._target_path)
        except (KeyError, IndexError, AttributeError) as e:
            return GradeResult(
                grader_type=self.type,
                passed=False,
                score=0.0,
                notes=f"path {self._target_path!r} did not resolve: {e}",
                metadata={"target": self._target_path, "mode": self._mode, "needles": self._needles},
            )

        haystack = raw if isinstance(raw, str) else json.dumps(raw, default=str)
        if not self._case_sensitive:
            haystack_cmp = haystack.lower()
            needles_cmp = [n.lower() for n in self._needles]
        else:
            haystack_cmp = haystack
            needles_cmp = list(self._needles)

        hits = [n for n, c in zip(self._needles, needles_cmp, strict=True) if c in haystack_cmp]
        misses = [n for n in self._needles if n not in hits]

        if self._mode == "any_of":
            passed = bool(hits)
            notes = (
                f"found {hits[0]!r} in {self._target_path}"
                if passed
                else f"none of {self._needles!r} found in {self._target_path}"
            )
        else:
            passed = not misses
            notes = (
                f"all of {self._needles!r} found in {self._target_path}"
                if passed
                else f"missing {misses!r} in {self._target_path}"
            )

        return GradeResult(
            grader_type=self.type,
            passed=passed,
            score=1.0 if passed else 0.0,
            notes=notes,
            metadata={
                "target": self._target_path,
                "mode": self._mode,
                "needles": self._needles,
                "hits": hits,
                "misses": misses,
                "case_sensitive": self._case_sensitive,
            },
        )
