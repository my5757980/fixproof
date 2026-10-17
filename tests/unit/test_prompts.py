"""Worker guidance learned from real runs (2026-10-16/17, psf__requests-1142)."""

from __future__ import annotations

from fixproof.agent import prompts
from fixproof.models import Task, TaskKind


def test_the_worker_is_told_not_to_leave_scratch_files_in_the_patch() -> None:
    system = prompts.worker_system_prompt()
    assert "scratch" in system and "ends up in the patch" in system
    assert "run_command" in system


def test_the_reproduction_is_one_test_and_nothing_else() -> None:
    task = Task(kind=TaskKind.DESCRIPTION, value="GET requests send Content-Length.")
    message = prompts.reproduce_message(task, prompts.DEFAULT_PLAN, ["requests/models.py"], None)
    assert "ONE new pytest test" in message
    assert "only this one test in the file" in message
