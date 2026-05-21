"""Target Protocol — what a tool-bearing system under test looks like to the runner.

A Target owns: (1) the Anthropic tool definitions handed to the model,
(2) the dispatch from tool name + input to a JSON-native result. Each
suite YAML names exactly one target by registry key.

For v0.1 every target invokes Python callables in-process. A future
target could speak MCP stdio (spawn the server, frame JSON-RPC); the
seam is the `dispatch` method — runner.py never imports the target's
internals. See targets/netsuite_saved_search.py for the TODO marking
where that swap would happen.
"""

from __future__ import annotations

from typing import Any, Protocol


class Target(Protocol):
    name: str

    def tool_definitions(self) -> list[dict[str, Any]]:
        """Anthropic tool schema list — `name`, `description`, `input_schema` per tool."""
        ...

    def dispatch(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        """Invoke a tool by name. Return a JSON-native value or raise.

        Exceptions are caught by the runner and surfaced as tool_result
        with `is_error=True`. The model sees the exception text so it
        can recover (matches MCP behavior for tool errors).
        """
        ...


def get_target(name: str, fixtures_dir: str) -> Target:
    """Construct a target by registry key. Imports are lazy so a missing
    optional dependency for one target doesn't break the harness."""
    if name == "netsuite_saved_search":
        from .targets.netsuite_saved_search import NetsuiteSavedSearchTarget

        return NetsuiteSavedSearchTarget(fixtures_dir=fixtures_dir)
    raise ValueError(
        f"unknown target {name!r}. Register it in claude_eval_harness/target.py."
    )
