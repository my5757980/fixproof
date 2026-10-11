"""Parallel hypotheses (User Story 3): branches from the repro snapshot, smallest verified wins."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fixproof.agent.orchestrator import RunRequest
from fixproof.events import EventType
from fixproof.models import (
    AttemptStatus,
    Budget,
    ModelRole,
    OutcomeLabel,
    Report,
    RunMode,
    StopReason,
)
from tests.fakes.calc_repo import REPO_URL
from tests.fakes.fake_executor import FakeExecutor
from tests.fakes.fake_model import reply_json, reply_text
from tests.fakes.parallel import HYPOTHESES, BranchScripts, parallel_planner
from tests.fakes.scenario import ISSUE_TASK, Scenario, make_scenario, plan_reply, report_reply


def make_parallel(
    tmp_runs_dir: Path,
    *,
    planner: list[Any] | None = None,
    budget: Budget | None = None,
    delay_s: float = 0.01,
) -> tuple[Scenario, BranchScripts]:
    scripts = BranchScripts()
    s = make_scenario(
        tmp_runs_dir,
        planner=planner if planner is not None else parallel_planner(),
        worker=scripts.worker_queue(),
        executor=FakeExecutor(delay_s=delay_s),
        budget=budget,
    )
    return s, scripts


async def run_parallel(s: Scenario, *, max_parallel: int = 3, exhaustive: bool = False) -> Any:
    request = RunRequest(
        repo_url=REPO_URL,
        task=ISSUE_TASK,
        mode=RunMode.PARALLEL,
        max_parallel=max_parallel,
        exhaustive=exhaustive,
    )
    return await s.orchestrator.run(request)


def load_report(s: Scenario) -> Report:
    return Report.model_validate_json((s.run_dir / "report.json").read_text(encoding="utf-8"))


async def test_hypotheses_become_attempts_from_the_repro_snapshot(tmp_runs_dir: Path) -> None:
    s, _ = make_parallel(tmp_runs_dir)
    run = await run_parallel(s)

    [hypotheses] = s.events(EventType.HYPOTHESES)
    assert [item["id"] for item in hypotheses.data["items"]] == ["h1", "h2", "h3"]
    repro = next(e for e in s.events(EventType.SNAPSHOT) if e.data["label"] == "repro")
    assert [a.id for a in run.attempts] == ["a1", "a2", "a3"]
    assert {a.start_snapshot.image_id for a in run.attempts} == {repro.data["image_id"]}
    assert [a.hypothesis.id for a in run.attempts if a.hypothesis] == ["h1", "h2", "h3"]
    finished = s.events(EventType.ATTEMPT_FINISHED)
    assert sorted(e.attempt_id for e in finished if e.attempt_id) == ["a1", "a2", "a3"]
    assert s.events(EventType.RUN_STARTED)[0].data["mode"] == "parallel"


async def test_the_first_verified_branch_cancels_the_others(tmp_runs_dir: Path) -> None:
    s, _ = make_parallel(tmp_runs_dir)
    run = await run_parallel(s)

    assert run.label is OutcomeLabel.VERIFIED and run.stop_reason is StopReason.COMPLETED
    status = {a.id: a.status for a in run.attempts}
    assert status["a1"] is AttemptStatus.VERIFIED
    assert status["a2"] is AttemptStatus.CANCELLED
    rows = {row.hypothesis_id: row for row in load_report(s).hypotheses}
    assert rows["h2"].attempt_status is AttemptStatus.CANCELLED and "h1" in rows["h2"].why
    patch = (s.run_dir / "patch.diff").read_text(encoding="utf-8")
    assert "+    return a + b" in patch and "result = a + b" not in patch


async def test_exhaustive_mode_picks_the_smallest_verified_change(tmp_runs_dir: Path) -> None:
    s, _ = make_parallel(tmp_runs_dir)
    run = await run_parallel(s, exhaustive=True)

    report = load_report(s)
    rows = {row.hypothesis_id: row for row in report.hypotheses}
    assert rows["h1"].label is OutcomeLabel.VERIFIED and rows["h2"].label is OutcomeLabel.VERIFIED
    assert rows["h3"].label is OutcomeLabel.NOT_VERIFIED
    assert rows["h1"].changed_lines is not None and rows["h2"].changed_lines is not None
    assert rows["h1"].changed_lines < rows["h2"].changed_lines
    assert "fewest changed lines" in rows["h1"].why
    assert "h1" in rows["h2"].why and "reproduction" in rows["h3"].why
    assert run.label is OutcomeLabel.VERIFIED
    assert "result = a + b" not in (s.run_dir / "patch.diff").read_text(encoding="utf-8")
    markdown = (s.run_dir / "report.md").read_text(encoding="utf-8")
    assert "## Hypotheses" in markdown and "add() should multiply." in markdown


async def test_no_more_than_max_parallel_branches_run_at_once(tmp_runs_dir: Path) -> None:
    """``--parallel N`` asks for at most N hypotheses and runs at most N branches at once."""
    s, _ = make_parallel(tmp_runs_dir)
    run = await run_parallel(s, max_parallel=2, exhaustive=True)

    [hypotheses] = s.events(EventType.HYPOTHESES)
    assert [item["id"] for item in hypotheses.data["items"]] == ["h1", "h2"]
    assert [a.id for a in run.attempts] == ["a1", "a2"]
    assert s.executor.max_active <= 2
    assert {e.attempt_id for e in s.events(EventType.TOOL_CALL) if e.attempt_id} == {"a1", "a2"}


async def test_branches_share_the_run_budget(tmp_runs_dir: Path) -> None:
    budget = Budget(max_steps=14, max_seconds=900, max_cost_usd=1.0)
    s, scripts = make_parallel(tmp_runs_dir, budget=budget)
    run = await run_parallel(s, exhaustive=True)

    steps = [e for e in s.events(EventType.MODEL_CALL)]
    assert len(steps) <= budget.max_steps
    assert sum(e.data["cost_usd"] for e in steps) <= budget.max_cost_usd
    assert {a.status for a in run.attempts} == {AttemptStatus.BUDGET_EXHAUSTED}
    assert run.label is OutcomeLabel.NOT_VERIFIED
    assert run.stop_reason is StopReason.BUDGET_STEPS
    assert scripts.calls["h1"] == scripts.calls["h2"] == scripts.calls["h3"] == 2


async def test_invalid_hypotheses_json_is_repaired_once(tmp_runs_dir: Path) -> None:
    planner = [
        plan_reply(),
        plan_reply(),
        reply_text("Here are my ideas: first, maybe add() is wrong."),
        reply_json(HYPOTHESES),
        report_reply(),
    ]
    s, _ = make_parallel(tmp_runs_dir, planner=planner)
    run = await run_parallel(s)

    assert len(s.events(EventType.HYPOTHESES)) == 1
    assert run.label is OutcomeLabel.VERIFIED
    repair = [r for r in s.model.requests if r.role is ModelRole.PLANNER][3]
    assert "not valid JSON" in repair.text()


async def test_unusable_hypotheses_fall_back_to_a_single_path(tmp_runs_dir: Path) -> None:
    planner = [plan_reply(), plan_reply(), reply_text("no"), reply_text("still no"), report_reply()]
    s = make_scenario(tmp_runs_dir, planner=planner)  # single-path worker script
    run = await run_parallel(s)

    assert s.events(EventType.HYPOTHESES) == []
    assert any("single" in e.data["message"] for e in s.events(EventType.ERROR))
    assert run.label is OutcomeLabel.VERIFIED and [a.id for a in run.attempts] == ["a1"]
