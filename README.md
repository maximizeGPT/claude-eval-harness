# claude-eval-harness

A regression-diff eval harness for Anthropic tool-use agents. Suites are
YAML; runs are self-contained JSON; `harness diff` surfaces per-case
behavioral changes between two runs — including drift in LLM-judge
reasoning, not just pass/fail flips.

Each case is a prompt sent to a Claude model wired to a set of tools;
one or more graders score the resulting trace.

*v0.1, prototype. Tested against example workloads only. The run-JSON
schema is at v1; `harness diff` refuses to compare runs across schema
majors.*

## Install

```bash
git clone https://github.com/maximizeGPT/claude-eval-harness
cd claude-eval-harness
uv sync --extra netsuite
export ANTHROPIC_API_KEY=sk-ant-...
```

`ANTHROPIC_API_KEY` must be exported in the parent shell — `uv run`
inherits the environment but does not source any shell init. If you
keep secrets in a `.env`, the equivalent is:

```bash
uv run --env-file .env harness run evals/suites/netsuite_saved_search.yaml
```

`--env-file` is non-overriding: a var already set (even to empty) in
the parent shell wins. Unset it first if the .env should take precedence.

The `netsuite` extra installs the [netsuite-saved-search-mcp](https://github.com/maximizeGPT/netsuite-saved-search-mcp)
package, which the bundled example suite exercises. The target seam is
in place; a second target binding is the v0.2 proof point.

## Quick start

Run the bundled suite:

```bash
uv run harness run evals/suites/netsuite_saved_search.yaml
```

Or filter to one case:

```bash
uv run harness run evals/suites/netsuite_saved_search.yaml \
  --filter get_headers_metadata_detection
```

Diff two runs (the regression-detection use case):

```bash
uv run harness diff runs/<baseline>.json runs/<new>.json
```

## Worked example: dual-model baseline diff

The bundled NetSuite suite has 15 cases against
[netsuite-saved-search-mcp](https://github.com/maximizeGPT/netsuite-saved-search-mcp).
Running it twice — once against Claude Sonnet 4.6, once against Opus
4.7 — and diffing is the comparison this harness exists to produce.

```bash
uv run harness run evals/suites/netsuite_saved_search.yaml \
  --out runs/baseline-sonnet-4-6.json
uv run harness run evals/suites/netsuite_saved_search.yaml --model claude-opus-4-7 \
  --out runs/baseline-opus-4-7.json
uv run harness diff runs/baseline-sonnet-4-6.json runs/baseline-opus-4-7.json
```

Sonnet 4.6 scored 12/15. Opus 4.7 scored 13/15. The diff makes that
one-case difference visible alongside five behavioral changes that a
pass/fail-only view would miss.

```
== fixed (1) ==
  column_typo_recovery
    llm_judge: FAIL -> PASS (The assistant satisfies all rubric
              requirements: (1) attempted query_export twice — first
              with 'Acount' (typo), then with 'Account' (corrected);
              (2) the second attempt used column='Account' exactly;
              (3) ultimately surfaced 53 matching rows for Account=1200.)

== changed (5) ==
  anomaly_zero_activity_june
    contains: metadata drift while PASS
      - hits:   ['Jun 2024', 'June 2024', 'June'] -> ['Jun 2024']
      - misses: []                                 -> ['June 2024', 'June']
  get_headers_metadata_detection
    llm_judge: metadata drift while PASS
      - reasoning drift (Opus more concise; same verdict)
  multi_tool_orchestration
    llm_judge: metadata drift while FAIL
      - reasoning: 'The assistant fabricated findings about Account
                    1200 Sep 2024 ratio anomalies, document count
                    variances, and Sam Patel's entries that do not
                    exist in the actual detect_anomalies results.'
                -> 'The final response invents anomalies not present
                    in the detect_anomalies output by claiming a
                    "MEDIUM – Ratio anomaly (Account 1200, Sep 2024)"
                    with a 3.1x multiple and citing 17 rows, as well
                    as a "MEDIUM – Document-count variance (Sep 2024)"
                    finding.'
  path_traversal_blocked
    contains: PASS -> FAIL
      - Sonnet: "path traversal"  Opus: "traversal pattern" / "reject" /
                                       "escape the configured data root"
  wrong_answer_judge_fail
    llm_judge: metadata drift while PASS
      - reasoning drift (different phrasing; same verdict)

unchanged: 9
```

What the diff exposes:

- **`column_typo_recovery` — fixed by Opus.** Sonnet failed the
  recovery flow entirely: it identified the typo, named the right
  column, then stopped without ever retrying the query. Opus retried
  with the corrected column name and surfaced 53 matching rows. Same
  case, two models, opposite outcomes — the `fixed` bucket flags it
  immediately. This is the kind of model-strength signal upgrade-or-
  not decisions hinge on.

- **`multi_tool_orchestration` — shared hallucination, judge caught
  it.** Both Sonnet 4.6 and Opus 4.7 hallucinated anomalies not
  present in the underlying `detect_anomalies` output. The structural
  graders would have missed this; the `llm_judge` caught it. This is
  the case `llm_judge` earns its cost on.

- **`path_traversal_blocked` — model judgment held; server enforcement
  untested.** This case is a two-layer defense check: model judgment
  refusing obviously malicious requests + server-side
  `_resolve_under_root` rejecting paths that escape `NSMCP_ROOT`. Both
  models refused on judgment, never invoking the tool — the structural
  grader correctly fails (no tool call in trace), meaning the server
  boundary is not being exercised by this case. The interesting drift
  is on the `contains` grader: Sonnet says "path traversal", Opus says
  "traversal pattern" / "reject" / "escape the configured data root".
  Different vocabulary, same intent. A CI matcher tuned for one
  model's phrasing would silently miss the other's.

- **`anomaly_zero_activity_june` — phrasing fingerprint.** Sonnet uses
  all three labels ("Jun 2024", "June 2024", "June"); Opus uses only
  the abbreviated form. Not a regression — a fingerprint that would
  matter if downstream tooling matched on the long form.

## Cost

Full suite cost on the dual-baseline above: **Sonnet 4.6 = $0.54** model
+ **$0.009 judge** = $0.55 total; **Opus 4.7 = $3.20** model + **$0.011
judge** = $3.21 total. The judge overhead is roughly constant across
models (four `llm_judge`-graded cases, Haiku 4.5 by default). For CI
integration Sonnet is the default; Opus is the pre-release
verification pass.

Judge cost is reported separately from case cost in the per-case line
and run totals: `cost=$0.0136 (+$0.0014 judge) wall=5317 ms`. The
separation matters once a suite has enough `llm_judge` cases that
judge overhead becomes its own budget signal.

## Findings from the baseline runs

These came out of the dual-model run and are documented rather than
silently fixed:

- **`categorize_amortization` is the cost outlier.** When
  `categorize_by_memo`'s full breakdown is passed back through the
  model and re-stated, the case accounts for roughly 20% of total run
  cost on both baselines (Sonnet $0.107, Opus $0.644). A
  `truncate_tool_results` runner option lands in v0.2. Until then the
  cost is what it is.
- **Rigorous llm_judge rubrics are what made the hallucinations
  catchable.** A generic rubric ("did the assistant produce a
  reasonable summary?") would have rubber-stamped both runs. The
  case 13 rubric explicitly enumerates "the final response invents
  anomalies not present in the detect_anomalies output" as a fail
  condition; without that line, the hallucinations sail through.
- **Both models refuse the path-traversal prompt regardless of
  framing.** A previous draft of case 14 used "../../etc/passwd";
  the current draft frames it as a routine config read for a migration
  check. Both phrasings produce the same outcome on Sonnet 4.6 and
  Opus 4.7 — neither model invokes the tool. The server-side boundary
  is therefore tested only indirectly (via the structural grader's
  "no tool call" failure). A target binding that exposes raw HTTP
  could exercise the server path independent of model judgment; that's
  a v0.2 concern.
- **The case 12 rubric conflates two things.** It scores recovery
  from the column-name typo AND final-answer synthesis as one
  pass/fail axis. In the current baseline Sonnet fails on the
  recovery axis (never retries the query) and Opus passes both. But
  the rubric would mark a model FAIL if it nailed the recovery and
  bungled the synthesis — we observed that exact case on an earlier
  spliced run before the clean re-run, and it scored identically to
  Sonnet's "no recovery at all" failure here. A v0.2 refactor splits
  this into two separately-graded sub-cases so the recovery signal
  and the synthesis signal stay independent.
- **Case 15 uses `fixture_trace` to isolate the judge from model
  variance.** The harness can replay pre-built traces directly when
  meta-testing graders — case 15's trace lives at
  `evals/fixtures/traces/wrong_header_row.json` and the runner skips
  the model call entirely. This is the design choice that makes
  judge-regression testing legible.

## Commands

| Verb | Purpose |
|---|---|
| `run`  | Execute a suite, write a run JSON to `runs/` |
| `diff` | Compare two run JSONs case-by-case |
| `show` | Pretty-print one run (or one case with `--case`) |
| `list` | List runs in a directory, newest last |

Add `--help` to any verb for full options.

## Graders

Four graders ship in v0.1. Adding a fifth is one module in
`src/claude_eval_harness/graders/` plus one line in `graders/__init__.py`.

| Type | What it checks | Use when |
|---|---|---|
| `exact_match` | Extract a value from the trace at a dotted path; compare to expected | The MCP tool returned a deterministic primitive (`header_row`, `total_matched`) |
| `contains`    | Substring match against `final_text` or a tool result, any-of / all-of | The model's prose mentions a specific entity (account number, period label) |
| `structural`  | All-of requirements over the tool-call sequence (tool name, partial args, result fields) | Verifying the model used the right tool with the right arguments |
| `llm_judge`   | Separate Claude call evaluates the trace against a rubric, returns `{passed, reasoning}` | The "right answer" is open-ended; reserve for orchestration / recovery cases |

`llm_judge` has inherent variance — expect 5–10% disagreement across
runs on borderline cases. Treat judge graders as smoke tests, not
regression ground truth; `structural` and `exact_match` are
deterministic and are what `harness diff` should anchor on for true
regression detection. The judge has an `invert: true` flag for
meta-cases that test the judge itself (a deliberately wrong fixture
trace passed through; the case passes when the judge correctly fails
it).

The diff verb reports four kinds of case-level deltas: `regressed`
(passed → failed), `fixed` (failed → passed), `changed` (same
pass/fail but grader metadata drifted — the dual-baseline walkthrough
above shows what this looks like in practice), `unchanged`. The
console reporter prints all three changed-kinds prominently with
case-level detail.

## Run JSON schema

Each run is a single JSON file under `runs/`:

```json
{
  "schema_version": 1,
  "run_id": "20260521T190855Z-claude-sonnet-4-6-fd93",
  "harness_version": "0.1.0",
  "suite_path": "evals/suites/netsuite_saved_search.yaml",
  "suite_sha256": "ab12cd34...",
  "model": "claude-sonnet-4-6",
  "started_at": "2026-05-21T19:05:00Z",
  "ended_at":   "2026-05-21T19:08:55Z",
  "totals": {"cases": 15, "passed": 12, "failed": 3, "errored": 0},
  "cases": [
    {
      "id": "...",
      "status": "passed",
      "duration_ms": 1240,
      "trace": {
        "prompt": "...",
        "turns": [...],
        "tool_calls": [{"name": "...", "input": {...}, "result": {...}, ...}],
        "final_text": "...",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 250, "output_tokens": 30, "cost_usd": 0.006, "judge_cost_usd": 0.0}
      },
      "graders": [{"type": "...", "passed": true, "score": 1.0, "notes": "...", "metadata": {...}}]
    }
  ]
}
```

Cost is computed from per-1M-token rates in `client.py` and is
approximate — set `HARNESS_PRICING_JSON=path/to/prices.json` to
override. Token counts are recorded losslessly, so an outdated rate
doesn't invalidate the run.

## What this isn't

- **Not an MCP transport tester.** v0.1 calls the target's tool functions
  directly in-process. That's faster, deterministic, and shares the
  callsite the FastMCP server uses, but it does not exercise the stdio
  JSON-RPC framing. Transport correctness belongs in the MCP server's
  own test suite; this harness covers everything above that layer
  (tool selection, argument shape, multi-turn recovery, final answer).
- **Not a benchmarking tool.** Cases run sequentially with no batching
  or parallelism in v0.1. Use it for correctness regressions, not
  throughput numbers.
- **Not a flaky-test handler.** Each case runs once per `harness run`;
  if a case errors transiently, rerun the suite. No automatic retries.

## Contributing

```bash
uv run pytest
uv run mypy src
uv run ruff check src tests
```

All three should be clean.

## License

MIT. See [LICENSE](LICENSE).
