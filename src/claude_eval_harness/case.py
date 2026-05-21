"""Test case + grader spec dataclasses.

Loaded from suite YAML by config.py and consumed by runner.py and the
graders. Kept dependency-free so tests can construct cases directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GraderSpec:
    """Raw grader configuration read from the suite YAML.

    The grader registry in graders/__init__.py maps `type` to a concrete
    grader class; everything else lives in `config` and is interpreted by
    that class. Keeping it untyped here lets the harness stay grader-
    agnostic — adding a new grader doesn't touch this file.
    """

    type: str
    config: dict[str, Any]


@dataclass(frozen=True)
class TestCase:
    id: str
    prompt: str
    graders: list[GraderSpec]
    description: str = ""
    model: str | None = None        # per-case override of the suite default
    max_turns: int | None = None    # per-case override of the suite default
    metadata: dict[str, Any] = field(default_factory=dict)
    # When set, the runner skips the model call entirely and feeds the
    # named trace JSON directly to the graders. Used for meta-cases that
    # test the graders themselves and must not depend on model behavior.
    # Path is resolved relative to the suite YAML.
    fixture_trace: str | None = None


@dataclass(frozen=True)
class Suite:
    """The whole YAML doc, validated and ready to run."""

    name: str
    target: str                     # registry key into targets/
    fixtures_dir: str               # path relative to the YAML
    model: str
    max_turns: int
    cases: list[TestCase]
