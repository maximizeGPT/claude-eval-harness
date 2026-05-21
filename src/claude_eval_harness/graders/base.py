"""Grader Protocol + GradeResult dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from ..case import TestCase
    from ..trace import Trace


class GraderConfigError(ValueError):
    """Raised when a grader's YAML config is malformed."""


@dataclass(frozen=True)
class GradeResult:
    grader_type: str
    passed: bool
    score: float
    notes: str
    metadata: dict[str, Any] = field(default_factory=dict)


class Grader(Protocol):
    type: str

    def __init__(self, config: dict[str, Any]) -> None: ...

    def grade(self, case: "TestCase", trace: "Trace") -> GradeResult: ...
