"""claude-eval-harness — YAML-driven eval harness for Anthropic tool-use agents."""

__version__ = "0.1.0"

# Bump SCHEMA_VERSION when the on-disk run JSON shape changes in a way the
# diff verb can't read transparently. diff.py refuses cross-major comparisons.
SCHEMA_VERSION = 1
