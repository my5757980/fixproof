"""The benchmark task file ``bench/tasks.toml`` (FR-023).

Each task is a real, already-fixed bug. The hidden tests come from the official fix and are
used only to measure the verified-fix rate; they are never shown to the agent.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from fixproof.models import BenchmarkTask


def load_benchmark_tasks(path: Path) -> list[BenchmarkTask]:
    """Load and validate the benchmark tasks.

    Args:
        path: The TOML file with one ``[[tasks]]`` table per task.

    Returns:
        The tasks, in file order.

    Raises:
        ValueError: If a task is invalid or an ID repeats.
    """
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    tasks = [BenchmarkTask.model_validate(item) for item in data.get("tasks", [])]
    ids = [task.id for task in tasks]
    duplicates = sorted({task_id for task_id in ids if ids.count(task_id) > 1})
    if duplicates:
        raise ValueError(f"duplicate benchmark task IDs: {', '.join(duplicates)}")
    return tasks
