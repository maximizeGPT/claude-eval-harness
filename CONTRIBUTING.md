# Contributing to claude-eval-harness

Thanks for considering a contribution. This file covers the practical
shape of contributing — setup, tests, reporting, code style, and how
PRs land. The README's install section covers the user install path;
this file is for people changing code.

## Setting up locally

```bash
git clone https://github.com/maximizeGPT/claude-eval-harness.git
cd claude-eval-harness
uv sync --extra netsuite
export ANTHROPIC_API_KEY=sk-ant-...
```

`uv sync --extra netsuite` installs the netsuite-saved-search-mcp
target which the example suite exercises. Without it, `harness run`
against `evals/suites/netsuite_saved_search.yaml` will fail at target
binding.

## Running tests

```bash
uv run pytest                  # full suite minus live-API tests
uv run pytest -m live          # include live API tests (uses your key)
uv run ruff check src tests    # style + lint
uv run mypy --strict src       # type check
```

CI runs the same four commands (without `-m live`). Live API tests
gate on `ANTHROPIC_API_KEY` and self-skip when it's unset, so local
runs without the key are safe.

## Filing a useful bug report

Open an issue using the `[BUG]` template. The thing that makes a
report useful — and that I'll ask for if it's missing — is the
relevant run JSON:

```bash
ls runs/ | tail -1                # most recent run
cat runs/<that-file>.json         # paste relevant excerpt
```

The run JSON contains the full prompt, every tool call, every
grader's score, and the final verdict per case. Trim or redact any
content you don't want public, but keep the structural shape (case
id, status, trace.turns) intact — that's what makes the report
diagnosable.

If the bug is in `harness diff`, include both run JSONs (the
baseline and the comparison) so I can reproduce the diff locally.

## Code style

Python code follows the shape of what's already there — small
modules per concept (case.py, runner.py, target.py, etc.), pydantic
discriminated unions for verdict shapes, no shared mutable state
between cases. Type hints everywhere; mypy strict catches
regressions.

`ruff check` enforces the style budget (line length, import order,
unused locals). Match surrounding patterns rather than introducing
a new convention.

## Pull request flow

I (Mohammed Wasif, [@maximizeGPT](https://github.com/maximizeGPT))
am the sole maintainer right now. Expect ~48-hour response time on
PRs.

For anything that changes the run-JSON schema (version 1 today),
the `harness diff` output format, the grader API, or the target
binding shape — **open an issue first** so the design discussion
happens before the code review. PRs against a solid issue land in
days; PRs that surface design questions in the diff take weeks
because the conversation happens twice.

For everything else — bug fixes, test additions, doc improvements,
new grader implementations, additional target bindings — just open
the PR. Include a one-line note in `CHANGELOG.md` under
`[Unreleased]` if the change is user-facing.

A schema-breaking change requires bumping `schema_version`. Don't
add fields under existing versions; the version guard in
`harness diff` exists to make schema drift visible, not to be
silently bypassed.
