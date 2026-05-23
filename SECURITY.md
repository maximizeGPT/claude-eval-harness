# Security policy

## Supported versions

Only the latest minor release of the harness receives security fixes
during the v0.x line.

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | :white_check_mark: |
| < 0.1.0 | :x:                |

## Reporting a vulnerability

**Email rayedwasif@hotmail.com.** Do not file a public GitHub issue
for security reports — that just publishes the vulnerability before
there's a fix.

A useful report includes: a description of the issue, the affected
harness version, repro steps, and (if relevant) a redacted run JSON
file from the `runs/` directory showing the unsafe behavior. I'll
acknowledge within 48 hours and ship a patch on the v0.1.x line if
the issue confirms.

## Scope

**In scope** — anything that lets the harness leak the user's
Anthropic API key into a run JSON, the trace log, or any other
artifact the user could share. Cross-target leaks (a case from one
target sneaking state into a run of another target) are in scope.
The `harness diff` schema-version guard is in scope.

**Out of scope** — vulnerabilities in third-party dependencies
(anthropic SDK, pydantic, uv), in Anthropic's API itself, or in the
target MCP servers a suite exercises. File those upstream. Cases
that produce incorrect grader scores due to flaws in the grader's
heuristics are bugs, not security issues.
