"""Thin Anthropic SDK wrapper with cost + latency capture.

Pricing is a static table — Anthropic publishes per-1M-token rates and
they change occasionally; the eval harness records token counts losslessly
so a stale rate doesn't invalidate the run. Override via the
`HARNESS_PRICING_JSON` env var (path to JSON `{model: {input, output}}`)
if you need different numbers.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anthropic

# Per-1M-token rates in USD. Approximate as of 2026-Q2 — verify against
# anthropic.com/pricing for billing-grade numbers. Stored at /1M precision
# so the dollar math reads cleanly; the multiplication accounts for it.
DEFAULT_PRICING_USD_PER_MILLION: dict[str, dict[str, float]] = {
    "claude-opus-4-7":          {"input": 15.00, "output": 75.00},
    "claude-opus-4-7[1m]":      {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6":        {"input":  3.00, "output": 15.00},
    "claude-haiku-4-5-20251001":{"input":  1.00, "output":  5.00},
}


def load_pricing() -> dict[str, dict[str, float]]:
    """Resolve effective pricing table (env override > built-in defaults)."""
    override = os.environ.get("HARNESS_PRICING_JSON")
    if not override:
        return DEFAULT_PRICING_USD_PER_MILLION
    try:
        return json.loads(Path(override).read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"HARNESS_PRICING_JSON unreadable: {e}") from e


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute dollar cost. Unknown models cost 0.0 — recorded but flagged."""
    rates = load_pricing().get(model)
    if rates is None:
        return 0.0
    return (
        input_tokens * rates["input"] / 1_000_000
        + output_tokens * rates["output"] / 1_000_000
    )


@dataclass
class TimedResponse:
    """One raw Anthropic response plus the wall-clock latency to fetch it."""

    message: anthropic.types.Message
    duration_ms: int


class HarnessClient:
    """Wraps anthropic.Anthropic with one-shot timing.

    Keeping this thin means tests can swap in a stub client by mimicking
    the `create_message` signature — see tests/conftest.py.
    """

    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        self._client = client or anthropic.Anthropic()

    def create_message(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
        system: str | None = None,
    ) -> TimedResponse:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
            "tools": tools,
        }
        if system is not None:
            kwargs["system"] = system
        t0 = time.monotonic()
        msg = self._client.messages.create(**kwargs)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return TimedResponse(message=msg, duration_ms=elapsed_ms)
