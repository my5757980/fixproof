"""Shared pytest fixtures for the FixProof test suite (offline by default)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_runs_dir(tmp_path: Path) -> Path:
    """Return an empty directory to use as the runs/state directory in a test."""
    runs = tmp_path / "runs"
    runs.mkdir()
    return runs
