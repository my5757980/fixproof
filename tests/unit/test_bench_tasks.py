"""The seeded benchmark tasks are valid, real-looking, and keep their hidden tests hidden."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fixproof.bench.tasks import load_benchmark_tasks
from fixproof.models import TaskKind
from fixproof.repo.github import parse_repo_url

TASKS_FILE = Path(__file__).resolve().parents[2] / "bench" / "tasks.toml"


def test_seeded_tasks_are_valid() -> None:
    tasks = load_benchmark_tasks(TASKS_FILE)
    assert len(tasks) >= 3
    for task in tasks:
        parse_repo_url(task.repo_url)
        assert re.fullmatch(r"[0-9a-f]{40}", task.base_commit), task.id
        assert task.python in {"3.9", "3.10", "3.11", "3.12"}, task.id
        assert task.hidden_fail_to_pass, task.id
        assert task.task.kind is TaskKind.DESCRIPTION and task.task.value.strip()
        for node_id in (*task.hidden_fail_to_pass, *task.hidden_pass_to_pass):
            assert node_id not in task.task.value, f"{task.id} shows a hidden test"


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    entry = (
        '[[tasks]]\nid = "x"\nrepo_url = "https://github.com/a/b"\nbase_commit = "'
        + "a" * 40
        + '"\n[tasks.task]\nkind = "description"\nvalue = "bug"\n'
    )
    path = tmp_path / "tasks.toml"
    path.write_text(entry + entry, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_benchmark_tasks(path)
