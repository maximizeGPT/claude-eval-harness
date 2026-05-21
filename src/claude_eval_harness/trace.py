"""Trace records — everything the runner captures during one case.

Designed so a Trace can be serialized to JSON straight from the dataclass
graph (`dataclasses.asdict`) without custom encoders. Anything non-JSON-
native (datetimes, Pydantic models) gets coerced at the boundary in
runner.py / storage.py rather than here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """One tool invocation: what the model asked for, what the target returned."""

    name: str
    input: dict[str, Any]
    result: Any                     # JSON-native: dict | list | str | int | float | bool | None
    result_ok: bool                 # False when the target raised; result is the error string
    duration_ms: int


@dataclass
class Turn:
    """One model turn — either a text response, tool calls, or both."""

    role: str                       # "assistant"
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class Usage:
    """Token counts and dollar cost for one case.

    Costs are derived from per-1M-token rates in client.py and are an
    approximation — Anthropic's published prices change, and this harness
    does not subscribe to a live pricing feed. Treat the dollar number
    as guidance, not a billing record.

    `judge_cost_usd` is accounted separately: it covers calls made by
    llm_judge graders, which are scored against the trace produced by
    the case-under-test. Conflating them would hide whether judge
    spend is dominating the suite's cost profile.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd: float = 0.0
    judge_cost_usd: float = 0.0


@dataclass
class Trace:
    prompt: str
    turns: list[Turn] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)  # flat, in invocation order
    final_text: str = ""
    stop_reason: str = ""
    usage: Usage = field(default_factory=Usage)
    duration_ms: int = 0
