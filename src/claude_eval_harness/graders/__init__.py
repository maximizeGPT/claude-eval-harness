"""Grader registry. Adding a grader = one new module + one line here."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import GradeResult, Grader, GraderConfigError
from .contains import ContainsGrader
from .exact_match import ExactMatchGrader
from .llm_judge import LLMJudgeGrader
from .structural import StructuralGrader

if TYPE_CHECKING:
    from ..case import GraderSpec

GRADERS: dict[str, type[Grader]] = {
    "exact_match": ExactMatchGrader,
    "contains": ContainsGrader,
    "structural": StructuralGrader,
    "llm_judge": LLMJudgeGrader,
}


def build_grader(spec: "GraderSpec") -> Grader:
    cls = GRADERS.get(spec.type)
    if cls is None:
        raise GraderConfigError(
            f"unknown grader type {spec.type!r}. Registered: {sorted(GRADERS)}"
        )
    return cls(spec.config)


__all__ = ["GRADERS", "GradeResult", "Grader", "GraderConfigError", "build_grader"]
