---
name: Bug report
about: Something the harness did that you didn't expect
title: "[BUG] "
labels: bug
assignees: ''
---

## What happened

A clear description of the surprise. One or two sentences.

## What you expected

What the harness should have done instead. One or two sentences.

## Reproduction steps

```bash
# the exact commands you ran
```

## Run JSON (or diff output)

If the bug is in `harness run`, paste the relevant excerpt from the
run JSON — case id, status, trace.turns. If it's in `harness diff`,
paste both run JSONs (or links to them) and the diff output.

```json
<paste here>
```

Trim or redact any content you don't want public, but keep the
structural shape (case id, status, trace.turns).

## Environment

- Python version: <output of `python --version`>
- Harness version: <e.g. 0.1.0, or commit SHA if from main>
- `uv` version: <output of `uv --version`>
- Anthropic SDK version: <`uv tree | grep anthropic`>

## Anything else

Optional. Screenshots, related issues, hypotheses.
