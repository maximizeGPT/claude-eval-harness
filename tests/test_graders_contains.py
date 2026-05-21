"""Unit tests for the contains grader."""

from __future__ import annotations

import pytest

from claude_eval_harness.case import GraderSpec, TestCase
from claude_eval_harness.graders import build_grader
from claude_eval_harness.graders.base import GraderConfigError
from claude_eval_harness.trace import ToolCall, Trace, Turn


def _case(graders: list[GraderSpec]) -> TestCase:
    return TestCase(id="t", prompt="x", graders=graders)


def _trace(final_text: str = "header_row is 14", result: object = None) -> Trace:
    tc = ToolCall(
        name="get_headers",
        input={"file_path": "f.xls"},
        result=result if result is not None else {"header_row": 14, "headers": ["A", "B"]},
        result_ok=True,
        duration_ms=5,
    )
    return Trace(
        prompt="x",
        turns=[Turn(role="assistant", text=final_text, tool_calls=[tc])],
        tool_calls=[tc],
        final_text=final_text,
        stop_reason="end_turn",
    )


class TestContainsGrader:
    def test_any_of_pass(self) -> None:
        spec = GraderSpec(type="contains", config={"target": "final_text", "any_of": ["14", "fourteen"]})
        r = build_grader(spec).grade(_case([spec]), _trace())
        assert r.passed
        assert r.metadata["hits"] == ["14"]

    def test_any_of_fail(self) -> None:
        spec = GraderSpec(type="contains", config={"target": "final_text", "any_of": ["banana", "kiwi"]})
        r = build_grader(spec).grade(_case([spec]), _trace())
        assert not r.passed
        assert r.metadata["misses"] == ["banana", "kiwi"]

    def test_all_of_pass(self) -> None:
        spec = GraderSpec(type="contains", config={"target": "final_text", "all_of": ["header", "14"]})
        r = build_grader(spec).grade(_case([spec]), _trace())
        assert r.passed

    def test_all_of_partial_fails(self) -> None:
        spec = GraderSpec(type="contains", config={"target": "final_text", "all_of": ["header", "missing"]})
        r = build_grader(spec).grade(_case([spec]), _trace())
        assert not r.passed
        assert "missing" in r.metadata["misses"]

    def test_case_sensitive_distinguishes(self) -> None:
        # default is case-insensitive
        spec_ci = GraderSpec(type="contains", config={"target": "final_text", "any_of": ["HEADER"]})
        assert build_grader(spec_ci).grade(_case([spec_ci]), _trace()).passed
        spec_cs = GraderSpec(type="contains", config={"target": "final_text", "any_of": ["HEADER"], "case_sensitive": True})
        assert not build_grader(spec_cs).grade(_case([spec_cs]), _trace()).passed

    def test_searches_inside_tool_result_json(self) -> None:
        spec = GraderSpec(type="contains", config={"target": "tool_calls[0].result", "any_of": ["header_row"]})
        r = build_grader(spec).grade(_case([spec]), _trace())
        assert r.passed

    def test_missing_path_marks_failure(self) -> None:
        spec = GraderSpec(type="contains", config={"target": "tool_calls[5].result", "any_of": ["x"]})
        r = build_grader(spec).grade(_case([spec]), _trace())
        assert not r.passed
        assert "did not resolve" in r.notes

    def test_config_validation(self) -> None:
        with pytest.raises(GraderConfigError):
            build_grader(GraderSpec(type="contains", config={"any_of": ["x"]}))
        with pytest.raises(GraderConfigError):
            build_grader(GraderSpec(type="contains", config={"target": "final_text"}))
        with pytest.raises(GraderConfigError):
            build_grader(GraderSpec(type="contains", config={"target": "final_text", "any_of": ["x"], "all_of": ["y"]}))
        with pytest.raises(GraderConfigError):
            build_grader(GraderSpec(type="contains", config={"target": "final_text", "any_of": []}))
        with pytest.raises(GraderConfigError):
            build_grader(GraderSpec(type="contains", config={"target": "final_text", "any_of": [1, 2]}))
