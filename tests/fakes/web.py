"""Builders for RunManager and web tests: fakes for every run, plus a gate to hold runs open."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from fixproof.config import Settings
from fixproof.events import EventType, TraceEvent
from fixproof.models import ModelRole, SampleTask, Task, TaskKind
from fixproof.sandbox.executor import CommandResult
from fixproof.trace import TraceWriter
from fixproof.web.runs import RunFactories, RunManager
from tests.fakes.calc_repo import CALC_FILES, ISSUE_URL, REPO_URL, calc_behavior
from tests.fakes.fake_executor import FakeExecutor
from tests.fakes.fake_github import FakeGitHub
from tests.fakes.fake_model import FakeModelClient
from tests.fakes.scenario import happy_planner, happy_worker
from tests.fakes.settings import make_settings

SAMPLE = SampleTask(
    id="calc-add",
    title="calc: add() subtracts",
    repo_url=REPO_URL,
    ref=None,
    task=Task(kind=TaskKind.ISSUE, value=ISSUE_URL),
    expected_minutes=5,
)


class Day:
    """A controllable 'today' for daily limits."""

    def __init__(self, value: date = date(2026, 10, 20)) -> None:
        self.value = value

    def __call__(self) -> date:
        return self.value


class Fakes:
    """Per-run fakes; ``gate`` holds every run inside its first pytest command until set."""

    def __init__(self, github: FakeGitHub | None = None, *, gated: bool = False) -> None:
        self.github = github or FakeGitHub(CALC_FILES)
        self.gate = asyncio.Event()
        self.gated = gated
        self.executors: list[FakeExecutor] = []
        self.models: list[FakeModelClient] = []
        self.started = asyncio.Event()

    def model(self, settings: Settings) -> FakeModelClient:
        model = FakeModelClient()
        model.script(ModelRole.PLANNER, *happy_planner())
        model.script(ModelRole.WORKER, *happy_worker())
        self.models.append(model)
        return model

    def executor(self, settings: Settings, on_event: Callable[..., Any]) -> FakeExecutor:
        executor = FakeExecutor()
        executor.test_behavior = calc_behavior
        if self.gated:

            async def wait_for_gate(command: str, fs: dict[str, bytes]) -> CommandResult:
                self.started.set()
                await self.gate.wait()
                executor.rules.pop(0)  # later pytest runs use the normal simulation
                return executor._pytest(command, fs)

            executor.add_rule(r"python -m pytest", wait_for_gate)
        self.executors.append(executor)
        return executor

    def factories(self) -> RunFactories:
        return RunFactories(
            model=self.model, executor=self.executor, repo_source=lambda s: self.github
        )


def make_manager(
    tmp_path: Path,
    *,
    fakes: Fakes | None = None,
    settings: Settings | None = None,
    today: Day | None = None,
    **options: Any,
) -> tuple[RunManager, Fakes]:
    fakes = fakes or Fakes()
    settings = settings or make_settings(state_dir=tmp_path / "state")
    manager = RunManager(
        settings,
        factories=fakes.factories(),
        samples=[SAMPLE],
        replays_dir=tmp_path / "replays",
        today=today or Day(),
        **options,
    )
    return manager, fakes


def write_replay(replays_dir: Path, name: str, events: list[TraceEvent], title: str) -> None:
    """Store a recorded trace and add it to ``index.toml``."""
    replays_dir.mkdir(parents=True, exist_ok=True)
    writer = TraceWriter(replays_dir / f"{name}.jsonl")
    for event in events:
        writer(event)
    writer.close()
    finished = next(e for e in events if e.type is EventType.RUN_FINISHED)
    with (replays_dir / "index.toml").open("a", encoding="utf-8") as index:
        index.write(
            f'[[replays]]\nname = "{name}"\ntitle = "{title}"\n'
            f'label = "{finished.data["label"]}"\nrecorded_at = "2026-10-11T10:00:00Z"\n\n'
        )


async def wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    """Poll ``condition`` until it holds (event-loop friendly)."""
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.01)
