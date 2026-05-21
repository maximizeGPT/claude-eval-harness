"""Unit tests for the llm_judge grader.

The Anthropic client is stubbed via the `_client` config key — that
hook is documented in llm_judge.py specifically so tests don't have to
monkey-patch the SDK or burn judge tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from claude_eval_harness.case import GraderSpec, TestCase
from claude_eval_harness.graders import build_grader
from claude_eval_harness.graders.base import GraderConfigError
from claude_eval_harness.trace import ToolCall, Trace, Turn


@dataclass
class _Block:
    type: str
    name: str = ""
    input: dict[str, Any] = None  # type: ignore[assignment]
    text: str = ""


@dataclass
class _Usage:
    input_tokens: int
    output_tokens: int


@dataclass
class _Msg:
    content: list[_Block]
    stop_reason: str
    usage: _Usage


class _StubMessages:
    def __init__(self, scripted: _Msg) -> None:
        self.scripted = scripted
        self.captured: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> _Msg:
        self.captured = kwargs
        return self.scripted


class _StubClient:
    def __init__(self, msg: _Msg) -> None:
        self.messages = _StubMessages(msg)


def _case(graders: list[GraderSpec]) -> TestCase:
    return TestCase(id="t", prompt="x", graders=graders)


def _trace() -> Trace:
    tc = ToolCall(
        name="get_headers",
        input={"file_path": "sample_with_metadata.xls"},
        result={"header_row": 14, "headers": ["A"]},
        result_ok=True,
        duration_ms=5,
    )
    return Trace(
        prompt="What is the header_row?",
        turns=[Turn(role="assistant", text="14", tool_calls=[tc])],
        tool_calls=[tc],
        final_text="The header_row is 14.",
        stop_reason="end_turn",
    )


class TestLLMJudgeGrader:
    def test_judge_pass(self) -> None:
        msg = _Msg(
            content=[_Block(type="tool_use", name="record_verdict",
                            input={"passed": True, "reasoning": "Assistant identified row 14 correctly."})],
            stop_reason="tool_use",
            usage=_Usage(input_tokens=300, output_tokens=40),
        )
        spec = GraderSpec(type="llm_judge", config={"rubric": "Did the assistant report header_row=14?", "_client": _StubClient(msg)})
        r = build_grader(spec).grade(_case([spec]), _trace())
        assert r.passed
        assert r.score == 1.0
        assert "row 14" in r.notes
        assert r.metadata["judge_input_tokens"] == 300
        assert r.metadata["judge_output_tokens"] == 40

    def test_judge_fail(self) -> None:
        msg = _Msg(
            content=[_Block(type="tool_use", name="record_verdict",
                            input={"passed": False, "reasoning": "Assistant gave wrong row."})],
            stop_reason="tool_use",
            usage=_Usage(input_tokens=200, output_tokens=30),
        )
        spec = GraderSpec(type="llm_judge", config={"rubric": "Did the assistant get it right?", "_client": _StubClient(msg)})
        r = build_grader(spec).grade(_case([spec]), _trace())
        assert not r.passed
        assert "wrong row" in r.metadata["reasoning"]

    def test_judge_did_not_call_tool(self) -> None:
        """If the judge ignores the forced tool and emits text, we fail cleanly."""
        msg = _Msg(
            content=[_Block(type="text", text="I'll think about it.")],
            stop_reason="end_turn",
            usage=_Usage(input_tokens=100, output_tokens=10),
        )
        spec = GraderSpec(type="llm_judge", config={"rubric": "x", "_client": _StubClient(msg)})
        r = build_grader(spec).grade(_case([spec]), _trace())
        assert not r.passed
        assert "did not return" in r.notes

    def test_judge_request_shape(self) -> None:
        """Verify we send the right system, tools, and tool_choice to Anthropic."""
        msg = _Msg(
            content=[_Block(type="tool_use", name="record_verdict",
                            input={"passed": True, "reasoning": "ok"})],
            stop_reason="tool_use",
            usage=_Usage(input_tokens=100, output_tokens=10),
        )
        stub = _StubClient(msg)
        spec = GraderSpec(type="llm_judge", config={"rubric": "r", "_client": stub})
        build_grader(spec).grade(_case([spec]), _trace())

        captured = stub.messages.captured
        assert captured["tool_choice"] == {"type": "tool", "name": "record_verdict"}
        assert len(captured["tools"]) == 1
        assert captured["tools"][0]["name"] == "record_verdict"
        # Sanity: trace content reaches the judge.
        prompt_text = captured["messages"][0]["content"]
        assert "get_headers" in prompt_text
        assert "The header_row is 14." in prompt_text
        assert "What is the header_row?" in prompt_text

    def test_invert_flips_pass_to_fail(self) -> None:
        """invert: judge says PASS, grader records FAIL — used for meta-tests."""
        msg = _Msg(
            content=[_Block(type="tool_use", name="record_verdict",
                            input={"passed": True, "reasoning": "answer is right"})],
            stop_reason="tool_use",
            usage=_Usage(input_tokens=100, output_tokens=10),
        )
        spec = GraderSpec(type="llm_judge", config={"rubric": "x", "invert": True, "_client": _StubClient(msg)})
        r = build_grader(spec).grade(_case([spec]), _trace())
        assert not r.passed
        assert r.metadata["judge_said_pass"] is True
        assert r.metadata["inverted"] is True
        assert "[inverted]" in r.notes

    def test_invert_flips_fail_to_pass(self) -> None:
        """invert: judge says FAIL on a deliberately wrong response, grader records PASS."""
        msg = _Msg(
            content=[_Block(type="tool_use", name="record_verdict",
                            input={"passed": False, "reasoning": "wrong answer"})],
            stop_reason="tool_use",
            usage=_Usage(input_tokens=100, output_tokens=10),
        )
        spec = GraderSpec(type="llm_judge", config={"rubric": "x", "invert": True, "_client": _StubClient(msg)})
        r = build_grader(spec).grade(_case([spec]), _trace())
        assert r.passed
        assert r.metadata["judge_said_pass"] is False
        assert r.metadata["inverted"] is True

    def test_config_validation(self) -> None:
        with pytest.raises(GraderConfigError):
            build_grader(GraderSpec(type="llm_judge", config={}))
        with pytest.raises(GraderConfigError):
            build_grader(GraderSpec(type="llm_judge", config={"rubric": ""}))
        with pytest.raises(GraderConfigError):
            build_grader(GraderSpec(type="llm_judge", config={"rubric": "   "}))
