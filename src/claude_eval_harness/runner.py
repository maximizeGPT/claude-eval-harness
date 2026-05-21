"""Per-case agent loop.

Sends the prompt + tool defs to the model, executes tool calls against
the target, feeds results back, stops on `end_turn` or `max_turns`.
Captures everything into a Trace and computes cost from accumulated
token usage.
"""

from __future__ import annotations

import time
from typing import Any

from .case import TestCase
from .client import HarnessClient, cost_usd
from .target import Target
from .trace import ToolCall, Trace, Turn, Usage


class RunnerError(RuntimeError):
    """Raised when the runner can't complete a case (not a grader failure)."""


def run_case(
    case: TestCase,
    *,
    target: Target,
    client: HarnessClient,
    model: str,
    max_turns: int,
) -> Trace:
    """Run one case end-to-end and return its Trace.

    Tool errors don't raise — they're fed back to the model as
    is_error=True tool_result blocks, matching what the MCP transport
    does in production so the model has the same recovery surface.
    """
    effective_model = case.model or model
    effective_max_turns = case.max_turns or max_turns

    trace = Trace(prompt=case.prompt)
    messages: list[dict[str, Any]] = [{"role": "user", "content": case.prompt}]
    tools = target.tool_definitions()

    t0 = time.monotonic()
    for _turn in range(effective_max_turns):
        timed = client.create_message(model=effective_model, messages=messages, tools=tools)
        msg = timed.message

        _accumulate_usage(trace.usage, msg, effective_model)

        text_chunks: list[str] = []
        tool_calls: list[ToolCall] = []
        # Anthropic's content blocks are heterogeneous; walk by type rather
        # than relying on attribute presence so unknown block types in
        # future SDK versions surface as a clear error instead of being
        # silently dropped.
        for block in msg.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_chunks.append(block.text)
            elif btype == "tool_use":
                tc = _dispatch_tool(target, block.name, dict(block.input))
                tool_calls.append(tc)
                trace.tool_calls.append(tc)

        trace.turns.append(Turn(role="assistant", text="\n".join(text_chunks) or None, tool_calls=tool_calls))

        if msg.stop_reason == "end_turn":
            trace.stop_reason = "end_turn"
            trace.final_text = "\n".join(text_chunks).strip()
            break
        if msg.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": [_block_to_dict(b) for b in msg.content]})
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": _tool_use_id_for(msg.content, tc),
                        "content": _stringify_result(tc.result),
                        "is_error": not tc.result_ok,
                    }
                    for tc in tool_calls
                ],
            })
            continue
        # Any other stop reason (max_tokens, etc.) — record and exit.
        trace.stop_reason = msg.stop_reason or "unknown"
        trace.final_text = "\n".join(text_chunks).strip()
        break
    else:
        trace.stop_reason = "max_turns_exceeded"

    trace.duration_ms = int((time.monotonic() - t0) * 1000)
    trace.usage.cost_usd = cost_usd(
        effective_model,
        trace.usage.input_tokens,
        trace.usage.output_tokens,
    )
    return trace


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------

def _dispatch_tool(target: Target, name: str, input_: dict[str, Any]) -> ToolCall:
    t0 = time.monotonic()
    try:
        result = target.dispatch(name, input_)
        ok = True
    except Exception as e:
        # Tool errors are domain-level signals: column typos, path
        # traversal, missing files. Hand the model the exception text so
        # it can recover the same way it would over MCP stdio.
        result = f"{type(e).__name__}: {e}"
        ok = False
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return ToolCall(name=name, input=input_, result=result, result_ok=ok, duration_ms=elapsed_ms)


def _accumulate_usage(usage: Usage, msg: Any, model: str) -> None:
    u = getattr(msg, "usage", None)
    if u is None:
        return
    usage.input_tokens += getattr(u, "input_tokens", 0) or 0
    usage.output_tokens += getattr(u, "output_tokens", 0) or 0
    usage.cache_creation_input_tokens += getattr(u, "cache_creation_input_tokens", 0) or 0
    usage.cache_read_input_tokens += getattr(u, "cache_read_input_tokens", 0) or 0


def _block_to_dict(block: Any) -> dict[str, Any]:
    """Convert an Anthropic content block back into a dict for re-submission.

    The SDK accepts dicts in `messages[].content`, which is the easiest
    way to echo the assistant's tool_use blocks back when we feed the
    tool_result on the next turn.
    """
    btype = getattr(block, "type", None)
    if btype == "text":
        return {"type": "text", "text": block.text}
    if btype == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": dict(block.input)}
    raise RunnerError(f"unhandled content block type: {btype!r}")


def _tool_use_id_for(content: list[Any], call: ToolCall) -> str:
    """Find the tool_use_id Anthropic assigned for a given ToolCall.

    We match by (name, input) — both are unique within a single response
    in practice. Could fail if the model issues two identical tool calls
    in one turn; if that ever shows up, switch to position-based mapping.
    """
    for block in content:
        if (
            getattr(block, "type", None) == "tool_use"
            and block.name == call.name
            and dict(block.input) == call.input
        ):
            return block.id
    raise RunnerError(f"no tool_use block matches dispatched call {call.name}")


def _stringify_result(result: Any) -> str:
    """tool_result.content must be a string (or list of blocks). JSON-encode."""
    import json

    if isinstance(result, str):
        return result
    return json.dumps(result, default=str)
