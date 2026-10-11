"""Orchestrator harness on the calc repository, shared by integration and contract tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fixproof.agent.orchestrator import Orchestrator, RunRequest, new_event_bus
from fixproof.config import Settings
from fixproof.events import EventBus, EventType, TraceEvent
from fixproof.llm.client import ModelReply
from fixproof.models import Budget, ModelRole, Run, Task, TaskKind
from tests.fakes.calc_repo import (
    CALC_FILES,
    ISSUE_URL,
    REPO_URL,
    REPRO_PATH,
    REPRO_TEST,
    calc_behavior,
)
from tests.fakes.fake_executor import FakeExecutor
from tests.fakes.fake_github import FakeGitHub
from tests.fakes.fake_model import FakeModelClient, reply_json, reply_tool, reply_tools
from tests.fakes.settings import make_settings

ISSUE_TASK = Task(kind=TaskKind.ISSUE, value=ISSUE_URL)

# -- scripted model replies ----------------------------------------------------------------


def plan_reply(understanding: str = "add() subtracts instead of adding.") -> ModelReply:
    return reply_json(
        {
            "understanding": understanding,
            "steps": ["Reproduce with a failing test", "Fix calc/core.py", "Verify"],
            "suspected_files": ["calc/core.py"],
        }
    )


def report_reply() -> ModelReply:
    return reply_json(
        {
            "summary": "add() subtracted its arguments; it now adds them.",
            "root_cause_md": "`calc/core.py:3-3` returned `a - b` instead of `a + b`.",
            "citations": [{"path": "calc/core.py", "start_line": 1, "end_line": 3}],
        }
    )


def create_file_reply(path: str, content: str, purpose: str = "Reproduce the bug") -> ModelReply:
    """A ``create_file`` call (``reply_tool`` reserves ``content`` for the message text)."""
    return reply_tools(("create_file", {"path": path, "content": content, "purpose": purpose}))


def reproduce_replies(path: str = REPRO_PATH, content: str = REPRO_TEST) -> list[ModelReply]:
    return [
        reply_tool("search_code", pattern="def add"),
        reply_tool("read_file", path="calc/core.py"),
        create_file_reply(path, content),
        reply_tool("run_tests", selector=path, purpose="Confirm the reproduction fails"),
        reply_tool(
            "finish", summary="Reproduced: add(2, 3) returns -1.", root_cause="add() subtracts."
        ),
    ]


def fix_replies(old: str = "return a - b", new: str = "return a + b") -> list[ModelReply]:
    return [
        reply_tool("edit_file", path="calc/core.py", old_text=old, new_text=new, purpose="Fix"),
        reply_tool("run_tests", selector=REPRO_PATH, purpose="Check the fix"),
        reply_tool(
            "finish",
            summary="add() now adds.",
            root_cause="add() used subtraction.",
            citations=[{"path": "calc/core.py", "start_line": 1, "end_line": 3}],
        ),
    ]


def happy_planner() -> list[ModelReply]:
    """Initial plan, refined plan, and final report."""
    return [plan_reply(), plan_reply(), report_reply()]


def happy_worker() -> list[ModelReply]:
    return [*reproduce_replies(), *fix_replies()]


# -- harness -------------------------------------------------------------------------------


@dataclass
class Scenario:
    orchestrator: Orchestrator
    bus: EventBus
    executor: FakeExecutor
    model: FakeModelClient
    github: FakeGitHub
    settings: Settings
    runs_dir: Path

    @property
    def run_dir(self) -> Path:
        return self.runs_dir / self.bus.run_id

    async def run(self, task: Task = ISSUE_TASK, ref: str | None = None) -> Run:
        return await self.orchestrator.run(RunRequest(repo_url=REPO_URL, task=task, ref=ref))

    def events(self, *types: EventType) -> list[TraceEvent]:
        return [e for e in self.bus.history if not types or e.type in types]

    def types(self) -> list[EventType]:
        return [e.type for e in self.bus.history]

    def seq_of(self, event_type: EventType, **match: Any) -> int:
        """Sequence number of the first event of ``event_type`` whose data matches ``match``."""
        for event in self.bus.history:
            if event.type is event_type and all(event.data.get(k) == v for k, v in match.items()):
                return event.seq
        raise AssertionError(f"no {event_type} event matching {match}")


def make_scenario(
    runs_dir: Path,
    *,
    planner: list[Any] | None = None,
    worker: list[Any] | None = None,
    files: Mapping[str, str] | None = None,
    budget: Budget | None = None,
    settings: Settings | None = None,
    executor: FakeExecutor | None = None,
    github: FakeGitHub | None = None,
    **options: Any,
) -> Scenario:
    """Build an orchestrator wired to fakes; ``options`` go to ``Orchestrator``."""
    settings = settings or make_settings()
    bus = new_event_bus(settings)
    executor = executor or FakeExecutor()
    if executor.test_behavior is None:
        executor.test_behavior = calc_behavior
    model = FakeModelClient()
    model.script(ModelRole.PLANNER, *(happy_planner() if planner is None else planner))
    model.script(ModelRole.WORKER, *(happy_worker() if worker is None else worker))
    github = github or FakeGitHub(files or CALC_FILES)
    orchestrator = Orchestrator(
        settings=settings,
        model=model,
        executor=executor,
        repo_source=github,
        bus=bus,
        runs_dir=runs_dir,
        budget=budget or settings.budget_cli(),
        **options,
    )
    return Scenario(orchestrator, bus, executor, model, github, settings, runs_dir)
