"""Suite YAML loader and validator.

Errors are raised as ConfigError with a path-prefixed message so the user
sees which case/grader/field broke. Validation is intentionally narrow —
unknown top-level keys are rejected, but per-grader config is opaque
(graders validate their own config when graded).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from .case import GraderSpec, Suite, TestCase

_SUITE_KEYS = {"suite", "target", "fixtures_dir", "model", "max_turns", "cases"}
_CASE_KEYS = {
    "id", "description", "prompt", "graders", "model", "max_turns",
    "metadata", "fixture_trace",
}
_GRADER_REQUIRED = {"type"}


class ConfigError(ValueError):
    """Raised when a suite YAML is malformed or references unknown values."""


def load_suite(path: str | Path) -> tuple[Suite, str]:
    """Read and validate a suite YAML. Returns (suite, sha256_of_file_bytes).

    The hash is stored in each run's JSON so diff can warn when comparing
    runs from drifted suites without having to re-read both files.
    """
    p = Path(path)
    raw = p.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    doc = yaml.safe_load(raw)
    if not isinstance(doc, dict):
        raise ConfigError(f"{p}: top-level YAML must be a mapping, got {type(doc).__name__}")

    _reject_unknown(doc, _SUITE_KEYS, prefix=str(p))

    name = _require(doc, "suite", str, prefix=str(p))
    target = _require(doc, "target", str, prefix=str(p))
    fixtures_dir = _require(doc, "fixtures_dir", str, prefix=str(p))
    model = _require(doc, "model", str, prefix=str(p))
    max_turns = doc.get("max_turns", 10)
    if not isinstance(max_turns, int) or max_turns <= 0:
        raise ConfigError(f"{p}: max_turns must be a positive integer, got {max_turns!r}")

    raw_cases = doc.get("cases", [])
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ConfigError(f"{p}: 'cases' must be a non-empty list")

    cases = [_parse_case(c, prefix=f"{p}:cases[{i}]") for i, c in enumerate(raw_cases)]
    _check_unique_ids(cases, prefix=str(p))

    return (
        Suite(
            name=name,
            target=target,
            fixtures_dir=fixtures_dir,
            model=model,
            max_turns=max_turns,
            cases=cases,
        ),
        sha,
    )


def _parse_case(raw: Any, *, prefix: str) -> TestCase:
    if not isinstance(raw, dict):
        raise ConfigError(f"{prefix}: case must be a mapping, got {type(raw).__name__}")
    _reject_unknown(raw, _CASE_KEYS, prefix=prefix)

    case_id = _require(raw, "id", str, prefix=prefix)
    prompt = _require(raw, "prompt", str, prefix=prefix)
    raw_graders = raw.get("graders", [])
    if not isinstance(raw_graders, list) or not raw_graders:
        raise ConfigError(f"{prefix}: 'graders' must be a non-empty list")
    graders = [
        _parse_grader(g, prefix=f"{prefix}.graders[{i}]")
        for i, g in enumerate(raw_graders)
    ]

    return TestCase(
        id=case_id,
        prompt=prompt,
        graders=graders,
        description=raw.get("description", ""),
        model=raw.get("model"),
        max_turns=raw.get("max_turns"),
        metadata=raw.get("metadata", {}) or {},
        fixture_trace=raw.get("fixture_trace"),
    )


def _parse_grader(raw: Any, *, prefix: str) -> GraderSpec:
    if not isinstance(raw, dict):
        raise ConfigError(f"{prefix}: grader must be a mapping, got {type(raw).__name__}")
    missing = _GRADER_REQUIRED - raw.keys()
    if missing:
        raise ConfigError(f"{prefix}: missing required key(s): {sorted(missing)}")
    type_ = raw["type"]
    if not isinstance(type_, str):
        raise ConfigError(f"{prefix}.type: must be a string, got {type(type_).__name__}")
    config = {k: v for k, v in raw.items() if k != "type"}
    return GraderSpec(type=type_, config=config)


def _require(d: dict[str, Any], key: str, typ: type, *, prefix: str) -> Any:
    if key not in d:
        raise ConfigError(f"{prefix}: missing required key {key!r}")
    val = d[key]
    if not isinstance(val, typ):
        raise ConfigError(
            f"{prefix}.{key}: expected {typ.__name__}, got {type(val).__name__}"
        )
    return val


def _reject_unknown(d: dict[str, Any], allowed: set[str], *, prefix: str) -> None:
    extra = d.keys() - allowed
    if extra:
        raise ConfigError(f"{prefix}: unknown key(s) {sorted(extra)} (allowed: {sorted(allowed)})")


def _check_unique_ids(cases: list[TestCase], *, prefix: str) -> None:
    seen: set[str] = set()
    for c in cases:
        if c.id in seen:
            raise ConfigError(f"{prefix}: duplicate case id {c.id!r}")
        seen.add(c.id)
