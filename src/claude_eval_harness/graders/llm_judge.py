"""llm_judge grader — separate Claude call evaluates the trace against a rubric.

The judge sees the case prompt, the full tool-call sequence, and the
assistant's final text. It returns `{passed: bool, reasoning: string}`
via a forced tool call (the cleanest way to get structured output from
Claude — see https://docs.anthropic.com/en/docs/build-with-claude/tool-use ).

Variance: judges disagree ~5–10% across runs on borderline cases. The
README documents this; consume judge results as smoke tests, not ground
truth for regression detection.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

import anthropic

from .base import GradeResult, GraderConfigError

if TYPE_CHECKING:
    from ..case import TestCase
    from ..trace import Trace


DEFAULT_JUDGE_MODEL = "claude-haiku-4-5-20251001"
_RECORD_VERDICT_TOOL = {
    "name": "record_verdict",
    "description": (
        "Record the verdict. Call this exactly once after evaluating the "
        "trace against the rubric. Do not call any other tool."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "passed": {
                "type": "boolean",
                "description": "true if the trace satisfies the rubric, false otherwise",
            },
            "reasoning": {
                "type": "string",
                "description": "One or two sentences explaining the verdict.",
            },
        },
        "required": ["passed", "reasoning"],
    },
}

_JUDGE_SYSTEM = (
    "You are an evaluator scoring a Claude assistant's response against a "
    "user-supplied rubric. You will be shown: (1) the rubric, (2) the user's "
    "prompt, (3) the tool calls the assistant made and what they returned, "
    "(4) the assistant's final text. Decide whether the rubric is satisfied "
    "and call the record_verdict tool exactly once with passed and reasoning. "
    "Do not call any other tool. Be strict — pass only when the rubric is "
    "clearly met."
)


class LLMJudgeGrader:
    type = "llm_judge"

    def __init__(self, config: dict[str, Any]) -> None:
        if "rubric" not in config:
            raise GraderConfigError("llm_judge grader requires 'rubric'")
        rubric = config["rubric"]
        if not isinstance(rubric, str) or not rubric.strip():
            raise GraderConfigError("llm_judge grader: 'rubric' must be a non-empty string")
        self._rubric: str = rubric
        self._model: str = config.get("model", DEFAULT_JUDGE_MODEL)
        # `invert` makes the grader pass when the judge says NO. Used only
        # for meta-cases that test the judge itself — e.g. a deliberately
        # wrong assistant response that the judge should correctly fail.
        # Misuse will mask bugs, so the default is False and the YAML must
        # opt in explicitly per case.
        self._invert: bool = bool(config.get("invert", False))
        # Injected client for testing — falls back to a real Anthropic client.
        self._client: anthropic.Anthropic | None = config.get("_client")

    def grade(self, case: "TestCase", trace: "Trace") -> GradeResult:
        client = self._client or anthropic.Anthropic()
        prompt = _build_judge_prompt(rubric=self._rubric, case_prompt=trace.prompt, trace=trace)
        try:
            message = client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=_JUDGE_SYSTEM,
                tools=[_RECORD_VERDICT_TOOL],
                tool_choice={"type": "tool", "name": "record_verdict"},
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as e:
            return GradeResult(
                grader_type=self.type,
                passed=False,
                score=0.0,
                notes=f"judge API call failed: {type(e).__name__}: {e}",
                metadata={"judge_model": self._model, "error": str(e)},
            )

        verdict = _extract_verdict(message)
        if verdict is None:
            return GradeResult(
                grader_type=self.type,
                passed=False,
                score=0.0,
                notes="judge did not return a record_verdict tool call",
                metadata={"judge_model": self._model, "stop_reason": message.stop_reason},
            )

        usage = getattr(message, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) if usage else 0
        out_tok = getattr(usage, "output_tokens", 0) if usage else 0

        judge_said_pass = bool(verdict["passed"])
        passed = (not judge_said_pass) if self._invert else judge_said_pass
        reasoning = verdict.get("reasoning", "")
        notes = reasoning.strip()[:280]
        if self._invert:
            notes = f"[inverted] judge said {'PASS' if judge_said_pass else 'FAIL'}: {notes}"

        return GradeResult(
            grader_type=self.type,
            passed=passed,
            score=1.0 if passed else 0.0,
            notes=notes,
            metadata={
                "judge_model": self._model,
                "reasoning": reasoning,
                "judge_said_pass": judge_said_pass,
                "inverted": self._invert,
                "judge_input_tokens": in_tok,
                "judge_output_tokens": out_tok,
            },
        )


# ---------------------------------------------------------------------------
# Prompt construction.
# ---------------------------------------------------------------------------

def _build_judge_prompt(*, rubric: str, case_prompt: str, trace: "Trace") -> str:
    lines = [
        "# Rubric",
        rubric.strip(),
        "",
        "# User prompt",
        case_prompt.strip(),
        "",
        "# Assistant tool calls",
    ]
    if not trace.tool_calls:
        lines.append("(none)")
    for i, call in enumerate(trace.tool_calls):
        result_preview = call.result if isinstance(call.result, str) else json.dumps(call.result, default=str)
        if len(result_preview) > 1500:
            result_preview = result_preview[:1500] + " ...[truncated]"
        ok = "ok" if call.result_ok else "ERR"
        lines.append(f"[{i}] {call.name}({json.dumps(call.input, default=str)}) -> [{ok}]")
        lines.append(f"    result: {result_preview}")
    lines.extend([
        "",
        "# Assistant final text",
        trace.final_text.strip() or "(empty)",
        "",
        "Call record_verdict with your decision.",
    ])
    return "\n".join(lines)


def _extract_verdict(message: anthropic.types.Message) -> dict[str, Any] | None:
    for block in message.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "record_verdict":
            return dict(block.input)
    return None
