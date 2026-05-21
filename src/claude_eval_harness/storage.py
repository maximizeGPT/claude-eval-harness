"""Read/write run JSON files.

The on-disk shape is documented in README.md. Diff and show consume this
schema; keep `schema_version` in lockstep with claude_eval_harness.SCHEMA_VERSION.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION, __version__
from .graders import GradeResult
from .trace import Trace


@dataclass
class CaseResult:
    id: str
    status: str                     # "passed" | "failed" | "errored"
    duration_ms: int
    trace: Trace | None
    graders: list[GradeResult]
    error: str | None = None


@dataclass
class RunRecord:
    run_id: str
    schema_version: int
    harness_version: str
    suite_path: str
    suite_sha256: str
    model: str
    started_at: str                 # ISO 8601 UTC
    ended_at: str
    totals: dict[str, int]
    cases: list[CaseResult] = field(default_factory=list)


def new_run_id(model: str) -> str:
    """Timestamp + model + 4-char hash. Sorts chronologically. Filename-safe."""
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    salt = hashlib.sha256(f"{ts}-{os.getpid()}-{model}".encode()).hexdigest()[:4]
    return f"{ts}-{model.replace('[', '_').replace(']', '_')}-{salt}"


def write_run(record: RunRecord, path: str | Path) -> None:
    Path(path).write_text(_to_json(record), encoding="utf-8")


def read_run(path: str | Path) -> RunRecord:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return _from_json(raw)


def _to_json(record: RunRecord) -> str:
    return json.dumps(asdict(record), indent=2, sort_keys=False, default=str)


def _from_json(raw: dict[str, Any]) -> RunRecord:
    cases = [_case_from_json(c) for c in raw.get("cases", [])]
    return RunRecord(
        run_id=raw["run_id"],
        schema_version=raw["schema_version"],
        harness_version=raw["harness_version"],
        suite_path=raw["suite_path"],
        suite_sha256=raw["suite_sha256"],
        model=raw["model"],
        started_at=raw["started_at"],
        ended_at=raw["ended_at"],
        totals=raw["totals"],
        cases=cases,
    )


def trace_from_json(t: dict[str, Any]) -> Trace:
    """Reconstruct a Trace from a JSON dict.

    Used by both run-JSON loading and by case fixture_trace files. Lives
    here rather than in trace.py because it depends on the on-disk
    shape, which storage.py owns.
    """
    from .trace import ToolCall, Turn, Usage

    turns = [
        Turn(
            role=tt["role"],
            text=tt.get("text"),
            tool_calls=[ToolCall(**tc) for tc in tt.get("tool_calls", [])],
        )
        for tt in t.get("turns", [])
    ]
    return Trace(
        prompt=t["prompt"],
        turns=turns,
        tool_calls=[ToolCall(**tc) for tc in t.get("tool_calls", [])],
        final_text=t.get("final_text", ""),
        stop_reason=t.get("stop_reason", ""),
        usage=Usage(**t.get("usage", {})),
        duration_ms=t.get("duration_ms", 0),
    )


def _case_from_json(raw: dict[str, Any]) -> CaseResult:
    t = raw.get("trace")
    trace: Trace | None = None if t is None else trace_from_json(t)
    return CaseResult(
        id=raw["id"],
        status=raw["status"],
        duration_ms=raw["duration_ms"],
        trace=trace,
        graders=[GradeResult(**g) for g in raw.get("graders", [])],
        error=raw.get("error"),
    )


def make_record(
    *,
    run_id: str,
    suite_path: str,
    suite_sha256: str,
    model: str,
    started_at: str,
    ended_at: str,
    cases: list[CaseResult],
) -> RunRecord:
    passed = sum(1 for c in cases if c.status == "passed")
    failed = sum(1 for c in cases if c.status == "failed")
    errored = sum(1 for c in cases if c.status == "errored")
    return RunRecord(
        run_id=run_id,
        schema_version=SCHEMA_VERSION,
        harness_version=__version__,
        suite_path=suite_path,
        suite_sha256=suite_sha256,
        model=model,
        started_at=started_at,
        ended_at=ended_at,
        totals={"cases": len(cases), "passed": passed, "failed": failed, "errored": errored},
        cases=cases,
    )
