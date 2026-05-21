"""Runner end-to-end with a stub Anthropic client — no API, no MCP.

Verifies the full assistant→tool_use→tool_result→end_turn loop without
spending tokens. Cost tracking is also asserted here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from claude_eval_harness.case import TestCase
from claude_eval_harness.client import HarnessClient, TimedResponse
from claude_eval_harness.runner import run_case


# ---------------------------------------------------------------------------
# Stub Anthropic SDK objects — duck-type just enough surface for the runner.
# ---------------------------------------------------------------------------

@dataclass
class _Block:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict[str, Any] = None  # type: ignore[assignment]


@dataclass
class _Usage:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class _Message:
    content: list[_Block]
    stop_reason: str
    usage: _Usage


class _StubClient:
    """Replays a queue of (model_msg, intended stop) responses."""

    def __init__(self, scripted: list[_Message]) -> None:
        self._scripted = list(scripted)
        self.calls: list[dict[str, Any]] = []

    def create_message(self, **kwargs: Any) -> TimedResponse:
        self.calls.append(kwargs)
        return TimedResponse(message=self._scripted.pop(0), duration_ms=1)


# ---------------------------------------------------------------------------
# A target that returns a canned tool result.
# ---------------------------------------------------------------------------

class _StubTarget:
    name = "stub"

    def tool_definitions(self) -> list[dict[str, Any]]:
        return [{"name": "get_headers", "description": "x", "input_schema": {"type": "object"}}]

    def dispatch(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        if tool_name == "get_headers":
            return {"headers": ["A"], "column_letters": {"A": "A"}, "header_row": 14}
        raise ValueError(tool_name)


def test_runner_completes_tool_use_loop() -> None:
    scripted = [
        _Message(
            content=[
                _Block(type="tool_use", id="toolu_1", name="get_headers", input={"file_path": "x.xls"})
            ],
            stop_reason="tool_use",
            usage=_Usage(input_tokens=100, output_tokens=20),
        ),
        _Message(
            content=[_Block(type="text", text="header_row is 14")],
            stop_reason="end_turn",
            usage=_Usage(input_tokens=150, output_tokens=10),
        ),
    ]
    stub = _StubClient(scripted)
    client = HarnessClient.__new__(HarnessClient)
    client._client = None  # type: ignore[assignment]
    client.create_message = stub.create_message  # type: ignore[method-assign]

    case = TestCase(id="t", prompt="What's the header row?", graders=[])
    trace = run_case(case, target=_StubTarget(), client=client, model="claude-opus-4-7", max_turns=4)

    assert trace.stop_reason == "end_turn"
    assert trace.final_text == "header_row is 14"
    assert len(trace.tool_calls) == 1
    assert trace.tool_calls[0].name == "get_headers"
    assert trace.tool_calls[0].result["header_row"] == 14
    assert trace.tool_calls[0].result_ok is True
    assert trace.usage.input_tokens == 250
    assert trace.usage.output_tokens == 30
    # claude-opus-4-7 priced at $15/M in, $75/M out:
    # 250 * 15/1M + 30 * 75/1M = 0.00375 + 0.00225 = 0.006
    assert abs(trace.usage.cost_usd - 0.006) < 1e-9


def test_runner_surfaces_tool_errors_to_model() -> None:
    class _ExplodingTarget(_StubTarget):
        def dispatch(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
            raise FileNotFoundError("nope")

    scripted = [
        _Message(
            content=[_Block(type="tool_use", id="toolu_1", name="get_headers", input={"file_path": "x.xls"})],
            stop_reason="tool_use",
            usage=_Usage(input_tokens=50, output_tokens=20),
        ),
        _Message(
            content=[_Block(type="text", text="Could not load that file.")],
            stop_reason="end_turn",
            usage=_Usage(input_tokens=80, output_tokens=10),
        ),
    ]
    stub = _StubClient(scripted)
    client = HarnessClient.__new__(HarnessClient)
    client._client = None  # type: ignore[assignment]
    client.create_message = stub.create_message  # type: ignore[method-assign]

    case = TestCase(id="t", prompt="open it", graders=[])
    trace = run_case(case, target=_ExplodingTarget(), client=client, model="claude-opus-4-7", max_turns=4)

    assert trace.tool_calls[0].result_ok is False
    assert "FileNotFoundError" in trace.tool_calls[0].result
    assert trace.stop_reason == "end_turn"
