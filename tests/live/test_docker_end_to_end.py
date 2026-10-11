"""Opt-in: a full run on the local Docker daemon (DEV executor) with a scripted model.

Everything is real except the model: the tarball upload, ``pip install`` (network on), the git
baseline, pytest with JUnit parsing (network off), file edits, verification, and the patch.
Run with ``FIXPROOF_DOCKER=1 uv run pytest -m docker`` (needs Docker and the python:3.12 image).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from fixproof.agent.orchestrator import Orchestrator, RunRequest, new_event_bus
from fixproof.events import EventType
from fixproof.models import ModelRole, OutcomeLabel, StopReason
from fixproof.sandbox.docker_dev import DockerExecutor
from tests.fakes.calc_repo import CALC_FILES, REPO_URL
from tests.fakes.fake_github import FakeGitHub
from tests.fakes.fake_model import FakeModelClient
from tests.fakes.scenario import ISSUE_TASK, happy_planner, happy_worker
from tests.fakes.settings import make_settings

DOCKER = os.environ.get("FIXPROOF_DOCKER", "") == "1"
pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not DOCKER, reason="Docker tests run only with FIXPROOF_DOCKER=1"),
]

# Without a pyproject.toml, setup installs only pytest; the tests import ``calc`` from the root.
FILES = {path: text for path, text in CALC_FILES.items() if path != "pyproject.toml"}


async def test_a_full_run_in_docker_is_verified(tmp_path: Path) -> None:
    settings = make_settings(executor="docker", state_dir=tmp_path)
    bus = new_event_bus(settings)

    def publish(kind: EventType, data: dict[str, Any]) -> None:
        bus.publish(kind, data)

    executor = DockerExecutor(on_event=publish)
    model = FakeModelClient()
    model.script(ModelRole.PLANNER, *happy_planner())
    model.script(ModelRole.WORKER, *happy_worker())
    orchestrator = Orchestrator(
        settings=settings,
        model=model,
        executor=executor,
        repo_source=FakeGitHub(FILES),
        bus=bus,
        runs_dir=tmp_path,
        budget=settings.budget_cli(),
    )
    try:
        run = await orchestrator.run(RunRequest(repo_url=REPO_URL, task=ISSUE_TASK))
    finally:
        await executor.close()

    errors = [e.data for e in bus.history if e.type is EventType.ERROR]
    assert run.stop_reason is StopReason.COMPLETED, errors
    assert run.label is OutcomeLabel.VERIFIED, errors
    patch = (tmp_path / run.id / "patch.diff").read_text(encoding="utf-8")
    assert "+    return a + b" in patch and "tests/test_fixproof_repro.py" in patch
    ops = [e for e in bus.history if e.type is EventType.SANDBOX_OP]
    assert ops and all(e.data["image_in"] for e in ops)
