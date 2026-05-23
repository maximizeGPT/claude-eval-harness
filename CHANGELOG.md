# Changelog

All notable changes to claude-eval-harness are documented here. Format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-05-21

First public release — regression-diff eval harness for Anthropic
tool-use agents. Suites are YAML; runs are self-contained JSON;
`harness diff` surfaces per-case behavioral changes between two runs,
including drift in LLM-judge reasoning, not just pass/fail flips.

### Added
- `harness run` — executes a YAML suite against a Claude model wired to
  a tool target, persists a self-contained run JSON under `runs/`.
- `harness diff` — compares two run JSONs, surfaces per-case status
  transitions (fixed / broken / changed / unchanged) and LLM-judge
  reasoning drift even when pass/fail is identical.
- `harness list` — enumerates available suites and recent runs.
- Run-JSON schema v1 with explicit `schema_version` guard; `diff`
  refuses to compare runs across schema majors so silent drift can't
  poison the verdict.
- Suite YAML format: case id, prompt, tool-call expectations, grader
  configs, optional per-case timeout.
- Target binding seam — the bundled `netsuite-saved-search-mcp` target
  is the v0.1.0 proof point. A second target binding is the v0.2 work.
- Graders: deterministic `regex`, `contains`, `tool_call_pattern`;
  LLM-as-judge graders with structured rubric output.
- Storage layout: `runs/<run-id>.json`, suites under `evals/suites/`,
  fixtures under `evals/fixtures/`.
- Baseline runs shipped under `runs/`: `baseline-sonnet-4-6.json`
  (12/15 passed) and `baseline-opus-4-7.json` (13/15 passed) against
  the netsuite saved-search suite.

### Known limitations
- **Schema v1 only.** A migration path to v2 isn't designed yet; for
  now, regenerate runs against the current schema when the harness
  upgrades.
- **One target binding.** A second target is the v0.2 proof point —
  v0.1 demonstrates the seam exists, not that it's been exercised at
  scale.
- **Live API tests gated on key.** Tests under `@pytest.mark.live`
  self-skip without `ANTHROPIC_API_KEY`; CI runs the non-live subset.

[Unreleased]: https://github.com/maximizeGPT/claude-eval-harness/compare/HEAD...HEAD
