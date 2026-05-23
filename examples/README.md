# examples

Minimal working eval suites you can run against your own
`ANTHROPIC_API_KEY` to see the harness end-to-end. Start here before
writing your own suites.

## `minimal.yaml`

Three cases against the bundled
[netsuite-saved-search-mcp](https://github.com/maximizeGPT/netsuite-saved-search-mcp)
target. Exercises the three grader types: `structural`,
`contains`, and `llm_judge`. Runs in ~30 seconds against Claude
Haiku 4.5 at a cost of a few cents per run.

```bash
git clone https://github.com/maximizeGPT/claude-eval-harness.git
cd claude-eval-harness
uv sync --extra netsuite
export ANTHROPIC_API_KEY=sk-ant-...
uv run harness run examples/minimal.yaml
```

Output lands under `runs/<run-id>.json`.

To see the diff machinery in action, run twice — once against Haiku,
once against Sonnet — then diff:

```bash
uv run harness run examples/minimal.yaml --out runs/haiku.json
uv run harness run examples/minimal.yaml --model claude-sonnet-4-6 --out runs/sonnet.json
uv run harness diff runs/haiku.json runs/sonnet.json
```

The diff output shape is the same one
[`README.md`'s worked example](../README.md#at-a-glance) shows —
`fixed` / `broken` / `changed` / `unchanged` buckets, with
per-grader drift annotations.

## What the three cases test

| Case                              | Tool         | Grader        | What it catches                                                |
|-----------------------------------|--------------|---------------|----------------------------------------------------------------|
| `list_exports_basic`              | list_exports | structural + contains | Target binding works; tool wired correctly; response surfaces returned filenames. |
| `get_headers_basic`               | get_headers  | structural + contains | Model calls the right tool with the right file_path; response includes the column names from the tool output. |
| `filtered_query_with_reasoning`   | query_export | structural + llm_judge | Filter shape is right; LLM judge confirms the response cites real row counts (no hallucination). |

This is the smallest set that exercises the three failure modes
worth catching automatically: wrong tool, wrong arguments,
hallucinated synthesis.

## Adding your own example

For a new target binding, drop a YAML next to `minimal.yaml` and
reference it in this README's table. The full suite format reference
is in the main [README's `## Run JSON schema`](../README.md#run-json-schema)
section.
