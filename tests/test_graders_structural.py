"""Unit tests for the structural grader."""

from __future__ import annotations

import pytest

from claude_eval_harness.case import GraderSpec, TestCase
from claude_eval_harness.graders import build_grader
from claude_eval_harness.graders.base import GraderConfigError
from claude_eval_harness.trace import ToolCall, Trace, Turn


def _case(graders: list[GraderSpec]) -> TestCase:
    return TestCase(id="t", prompt="x", graders=graders)


def _trace_with_query() -> Trace:
    tc = ToolCall(
        name="query_export",
        input={"file_path": "x.xls", "filters": [{"op": "eq", "column": "Account", "value": "1200"}]},
        result={"rows": [{"a": 1}], "total_matched": 45, "truncated": False},
        result_ok=True,
        duration_ms=10,
    )
    return Trace(
        prompt="x",
        turns=[Turn(role="assistant", text="ok", tool_calls=[tc])],
        tool_calls=[tc],
        final_text="ok",
        stop_reason="end_turn",
    )


class TestStructuralGrader:
    def test_tool_name_required(self) -> None:
        spec = GraderSpec(type="structural", config={"require": [{"tool": "query_export"}]})
        assert build_grader(spec).grade(_case([spec]), _trace_with_query()).passed

    def test_wrong_tool_fails(self) -> None:
        spec = GraderSpec(type="structural", config={"require": [{"tool": "get_headers"}]})
        r = build_grader(spec).grade(_case([spec]), _trace_with_query())
        assert not r.passed

    def test_partial_args_match(self) -> None:
        spec = GraderSpec(type="structural", config={"require": [
            {"tool": "query_export", "args": {"file_path": "x.xls"}}
        ]})
        assert build_grader(spec).grade(_case([spec]), _trace_with_query()).passed

    def test_nested_args_match(self) -> None:
        spec = GraderSpec(type="structural", config={"require": [
            {"tool": "query_export", "args": {
                "filters": [{"op": "eq", "column": "Account", "value": "1200"}]
            }}
        ]})
        assert build_grader(spec).grade(_case([spec]), _trace_with_query()).passed

    def test_comparator_passes(self) -> None:
        spec = GraderSpec(type="structural", config={"require": [
            {"tool": "query_export", "result": {"total_matched": {">=": 30}, "truncated": False}}
        ]})
        assert build_grader(spec).grade(_case([spec]), _trace_with_query()).passed

    def test_comparator_fails(self) -> None:
        spec = GraderSpec(type="structural", config={"require": [
            {"tool": "query_export", "result": {"total_matched": {">=": 100}}}
        ]})
        r = build_grader(spec).grade(_case([spec]), _trace_with_query())
        assert not r.passed
        assert "total_matched" in r.notes

    def test_between_comparator(self) -> None:
        spec_pass = GraderSpec(type="structural", config={"require": [
            {"tool": "query_export", "result": {"total_matched": {"between": [30, 60]}}}
        ]})
        spec_fail = GraderSpec(type="structural", config={"require": [
            {"tool": "query_export", "result": {"total_matched": {"between": [100, 200]}}}
        ]})
        assert build_grader(spec_pass).grade(_case([spec_pass]), _trace_with_query()).passed
        assert not build_grader(spec_fail).grade(_case([spec_fail]), _trace_with_query()).passed

    def test_result_ok_check(self) -> None:
        # error trace
        err = ToolCall(name="query_export", input={"file_path": "../etc/passwd"},
                       result="PathTraversalError: outside root", result_ok=False, duration_ms=1)
        err_trace = Trace(prompt="x", tool_calls=[err], final_text="blocked",
                          stop_reason="end_turn",
                          turns=[Turn(role="assistant", text="blocked", tool_calls=[err])])
        spec = GraderSpec(type="structural", config={"require": [
            {"tool": "query_export", "result_ok": False, "result_contains": "PathTraversalError"}
        ]})
        assert build_grader(spec).grade(_case([spec]), err_trace).passed

    def test_index_pins_position(self) -> None:
        spec = GraderSpec(type="structural", config={"require": [
            {"tool": "query_export", "index": 0}
        ]})
        assert build_grader(spec).grade(_case([spec]), _trace_with_query()).passed
        spec_bad = GraderSpec(type="structural", config={"require": [
            {"tool": "query_export", "index": 5}
        ]})
        r = build_grader(spec_bad).grade(_case([spec_bad]), _trace_with_query())
        assert not r.passed
        assert "out of range" in r.notes

    def test_all_requirements_must_pass(self) -> None:
        spec = GraderSpec(type="structural", config={"require": [
            {"tool": "query_export"},
            {"tool": "missing_tool"},
        ]})
        r = build_grader(spec).grade(_case([spec]), _trace_with_query())
        assert not r.passed
        assert any(req["ok"] for req in r.metadata["requirements"])
        assert any(not req["ok"] for req in r.metadata["requirements"])

    def test_config_validation(self) -> None:
        with pytest.raises(GraderConfigError):
            build_grader(GraderSpec(type="structural", config={}))
        with pytest.raises(GraderConfigError):
            build_grader(GraderSpec(type="structural", config={"require": [{}]}))
        with pytest.raises(GraderConfigError):
            build_grader(GraderSpec(type="structural", config={"require": []}))
