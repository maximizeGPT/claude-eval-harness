"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "evals" / "fixtures" / "netsuite"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR
