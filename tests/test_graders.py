"""Grader unit tests — no API calls, no MCP, pure transforms."""

from __future__ import annotations

import pytest

from claude_eval_harness.case import GraderSpec, TestCase
from claude_eval_harness.graders import build_grader
from claude_eval_harness.graders.base import GraderConfigError
from claude_eval_harness.trace import ToolCall, Trace, Turn, Usage


def _case(graders: list[GraderSpec]) -> TestCase:
    return TestCase(id="t", prompt="x", graders=graders)


def _trace_with_header_row(value: int) -> Trace:
    tc = ToolCall(
        name="get_headers",
        input={"file_path": "sample_with_metadata.xls"},
        result={"headers": ["A"], "column_letters": {"A": "A"}, "header_row": value},
        result_ok=True,
        duration_ms=5,
    )
    return Trace(
        prompt="x",
        turns=[Turn(role="assistant", text="14", tool_calls=[tc])],
        tool_calls=[tc],
        final_text="14",
        stop_reason="end_turn",
        usage=Usage(input_tokens=100, output_tokens=10),
    )


class TestExactMatchGrader:
    def test_pass_on_match(self) -> None:
        spec = GraderSpec(type="exact_match", config={"path": "tool_calls[0].result.header_row", "expected": 14})
        case = _case([spec])
        result = build_grader(spec).grade(case, _trace_with_header_row(14))
        assert result.passed
        assert result.score == 1.0
        assert result.metadata["actual"] == 14

    def test_fail_on_mismatch(self) -> None:
        spec = GraderSpec(type="exact_match", config={"path": "tool_calls[0].result.header_row", "expected": 14})
        case = _case([spec])
        result = build_grader(spec).grade(case, _trace_with_header_row(0))
        assert not result.passed
        assert result.score == 0.0
        assert result.metadata == {"path": "tool_calls[0].result.header_row", "expected": 14, "actual": 0}

    def test_missing_path_marks_failure_not_exception(self) -> None:
        spec = GraderSpec(type="exact_match", config={"path": "tool_calls[5].result.header_row", "expected": 14})
        case = _case([spec])
        result = build_grader(spec).grade(case, _trace_with_header_row(14))
        assert not result.passed
        assert "did not resolve" in result.notes

    def test_final_text_path_resolves(self) -> None:
        spec = GraderSpec(type="exact_match", config={"path": "final_text", "expected": "14"})
        case = _case([spec])
        result = build_grader(spec).grade(case, _trace_with_header_row(14))
        assert result.passed

    def test_missing_config_raises_at_construction(self) -> None:
        with pytest.raises(GraderConfigError):
            build_grader(GraderSpec(type="exact_match", config={"path": "final_text"}))
        with pytest.raises(GraderConfigError):
            build_grader(GraderSpec(type="exact_match", config={"expected": "x"}))

    def test_invalid_path_segment_rejected_at_construction(self) -> None:
        with pytest.raises(GraderConfigError):
            build_grader(GraderSpec(type="exact_match", config={"path": "tool_calls[0].result.[bad]", "expected": 1}))


class TestRegistry:
    def test_unknown_grader_type_raises(self) -> None:
        with pytest.raises(GraderConfigError):
            build_grader(GraderSpec(type="hypeometer", config={}))
