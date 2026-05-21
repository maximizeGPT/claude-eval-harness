"""Target binding for the netsuite-saved-search-mcp package.

The 7 MCP tools live in `netsuite_saved_search_mcp.tools` and
`netsuite_saved_search_mcp.anomalies` as plain Python functions. This
target hands the model the Anthropic tool schemas and dispatches calls
straight into those functions — no subprocess, no JSON-RPC framing.

# TODO(transport): swap the in-process dispatch for an MCP stdio client
#   when the harness needs to exercise the wire format. The seam is
#   `dispatch` below: spawn `netsuite-saved-search-mcp` as a subprocess,
#   speak JSON-RPC over its stdio, route `tools/call` and unwrap the
#   response. `tool_definitions` would query the server's `tools/list`
#   instead of the hand-written list here. For v0.1 the in-process path
#   is faster, deterministic, and pinned to the same callsite the
#   FastMCP server uses, so a transport-shaped bug is the only thing
#   the swap would catch — and that belongs in the MCP repo's own tests.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class NetsuiteSavedSearchTarget:
    name = "netsuite_saved_search"

    def __init__(self, fixtures_dir: str) -> None:
        # NSMCP_ROOT is how the MCP server scopes every file path the model
        # provides. Setting it here means relative paths in the model's tool
        # calls resolve to the fixtures dir, matching the deployed behavior.
        resolved = Path(fixtures_dir).resolve()
        if not resolved.is_dir():
            raise FileNotFoundError(f"fixtures_dir does not exist: {resolved}")
        os.environ["NSMCP_ROOT"] = str(resolved)
        # Clear the parsed-export cache so consecutive harness runs in the
        # same process don't return stale handles when fixtures change.
        from netsuite_saved_search_mcp.tools import clear_cache

        clear_cache()
        self._fixtures_dir = resolved

    # ------------------------------------------------------------------
    # Tool schema — fed verbatim to Anthropic's `tools` parameter.
    # ------------------------------------------------------------------

    def tool_definitions(self) -> list[dict[str, Any]]:
        predicate_schema = {
            "type": "object",
            "description": (
                "Discriminated union keyed on `op`. Allowed shapes: "
                "eq/ne (column, value), gt/gte/lt/lte (column, value), "
                "contains/not_contains (column, value, case_sensitive?), "
                "regex (column, pattern), "
                "date_range (column, start, end ISO 8601, inclusive?)."
            ),
            "properties": {
                "op": {"type": "string"},
                "column": {"type": "string"},
                "value": {},
                "pattern": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "case_sensitive": {"type": "boolean"},
                "inclusive": {"type": "boolean"},
            },
            "required": ["op", "column"],
        }
        measure_schema = {
            "type": "object",
            "properties": {
                "column": {"type": "string"},
                "op": {"type": "string", "enum": ["sum", "count", "avg", "min", "max"]},
                "alias": {"type": "string"},
            },
            "required": ["column", "op"],
        }
        return [
            {
                "name": "list_exports",
                "description": (
                    "List every NetSuite saved-search export (.xls) in a directory. "
                    "Returns one summary per file: row_count, header_count, header_row, "
                    "warning_count, date_range. Files that fail to parse return with "
                    "parse_error populated. Call this first to discover available files."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "directory": {
                            "type": "string",
                            "description": "Directory path, relative to NSMCP_ROOT or absolute under it.",
                        }
                    },
                    "required": ["directory"],
                },
            },
            {
                "name": "get_headers",
                "description": (
                    "Return the column headers of a NetSuite saved-search export, their "
                    "spreadsheet column letters (A, B, ..., AA), and the 0-indexed "
                    "header_row. Use before query_export / aggregate_export when you "
                    "don't already know the column names."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
            },
            {
                "name": "query_export",
                "description": (
                    "Filter rows by a list of predicates (AND-combined; empty list "
                    "returns everything). Optionally project to a subset of columns. "
                    "Implicit limit=1000; pass limit=0 to get total_matched without "
                    "fetching rows."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "filters": {"type": "array", "items": predicate_schema},
                        "columns": {"type": "array", "items": {"type": "string"}},
                        "limit": {"type": "integer", "minimum": 0},
                    },
                    "required": ["file_path"],
                },
            },
            {
                "name": "aggregate_export",
                "description": (
                    "Group rows by one or more columns; compute one measure per group. "
                    "Measure op is sum/count/avg/min/max. Use instead of query_export "
                    "when you want summary statistics rather than raw rows."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "group_by": {"type": "array", "items": {"type": "string"}},
                        "measures": {"type": "array", "items": measure_schema},
                    },
                    "required": ["file_path", "group_by", "measures"],
                },
            },
            {
                "name": "categorize_by_memo",
                "description": (
                    "Tag each row with a `_category` derived from case-insensitive "
                    "substring matches across one or more memo columns. First rule "
                    "whose keyword appears wins; rows matching nothing fall into "
                    "'Uncategorized'. Returns tagged rows plus a per-category count."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "memo_columns": {"type": "array", "items": {"type": "string"}},
                        "rules": {
                            "type": "object",
                            "additionalProperties": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                    },
                    "required": ["file_path", "memo_columns", "rules"],
                },
            },
            {
                "name": "detect_anomalies",
                "description": (
                    "Three checks against a GL-style export: zero_activity_period "
                    "(HIGH; month gaps inside the observed range), ratio_anomaly "
                    "(MEDIUM; (account, period) total > 2x the account's median), "
                    "document_count_variance (MEDIUM; period count > 2 stdev from "
                    "mean). Period column should be 'Jan 2024', 'January 2024', or "
                    "'2024-01'."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "account_column": {"type": "string"},
                        "amount_column": {"type": "string"},
                        "period_column": {"type": "string"},
                    },
                    "required": [
                        "file_path",
                        "account_column",
                        "amount_column",
                        "period_column",
                    ],
                },
            },
            {
                "name": "get_parse_warnings",
                "description": (
                    "Return parse warnings for the export at file_path. Warning kinds: "
                    "phantom_column, bad_datetime, encoding_recovery, empty_row_skipped. "
                    "Call this after any other tool reports a non-zero warning_count."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
            },
        ]

    # ------------------------------------------------------------------
    # Dispatch — the seam where a stdio transport would plug in.
    # ------------------------------------------------------------------

    def dispatch(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        from netsuite_saved_search_mcp import anomalies as _anomalies_mod
        from netsuite_saved_search_mcp import tools as _tools_mod
        from netsuite_saved_search_mcp.parser import Measure, ParseWarning

        if tool_name == "list_exports":
            return _to_jsonable(_tools_mod.list_exports(**tool_input))
        if tool_name == "get_headers":
            return _to_jsonable(_tools_mod.get_headers(**tool_input))
        if tool_name == "query_export":
            return _to_jsonable(
                _tools_mod.query_export(
                    file_path=tool_input["file_path"],
                    filters=_parse_predicates(tool_input.get("filters")),
                    columns=tool_input.get("columns"),
                    limit=tool_input.get("limit"),
                )
            )
        if tool_name == "aggregate_export":
            return _to_jsonable(
                _tools_mod.aggregate_export(
                    file_path=tool_input["file_path"],
                    group_by=tool_input["group_by"],
                    measures=[Measure(**m) for m in tool_input["measures"]],
                )
            )
        if tool_name == "categorize_by_memo":
            return _to_jsonable(_tools_mod.categorize_by_memo(**tool_input))
        if tool_name == "detect_anomalies":
            return _to_jsonable(_anomalies_mod.detect_anomalies(**tool_input))
        if tool_name == "get_parse_warnings":
            warnings: list[ParseWarning] = _tools_mod.get_parse_warnings(**tool_input)
            return [{"row": w.row, "kind": w.kind, "message": w.message} for w in warnings]
        raise ValueError(f"unknown tool: {tool_name}")


# ---------------------------------------------------------------------------
# Helpers — coerce Pydantic / dataclass / date results to JSON-native types.
# ---------------------------------------------------------------------------

def _to_jsonable(value: Any) -> Any:
    """Recursively coerce Pydantic models, dates, and dataclasses to JSON-native.

    Pydantic v2 models have `.model_dump(mode='json')` which already handles
    dates and nested models. Lists and dicts are walked so a list of
    ExportSummary objects also lands clean.
    """
    from datetime import date, datetime

    from pydantic import BaseModel

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    return value


def _parse_predicates(raw: list[dict[str, Any]] | None) -> list[Any]:
    """Map raw dicts back into the parser's typed predicate models.

    The MCP tool's signature takes the union type; passing raw dicts works
    because Pydantic discriminates on `op`, but constructing the models
    explicitly here gives us a cleaner error message when the model
    invents a malformed predicate.
    """
    if not raw:
        return []
    from netsuite_saved_search_mcp.parser import (
        ComparePredicate,
        ContainsPredicate,
        DateRangePredicate,
        EqPredicate,
        RegexPredicate,
    )

    classes = {
        "eq": EqPredicate,
        "ne": EqPredicate,
        "gt": ComparePredicate,
        "gte": ComparePredicate,
        "lt": ComparePredicate,
        "lte": ComparePredicate,
        "contains": ContainsPredicate,
        "not_contains": ContainsPredicate,
        "regex": RegexPredicate,
        "date_range": DateRangePredicate,
    }
    out: list[Any] = []
    for p in raw:
        op = p.get("op")
        cls = classes.get(op or "")
        if cls is None:
            raise ValueError(f"unknown predicate op: {op!r}")
        out.append(cls(**p))
    return out
