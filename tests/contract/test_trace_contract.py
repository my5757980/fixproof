"""Contract test: emitted traces match specs/001-verified-fix-agent/contracts/trace-events.md."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from fixproof.agent.report import report_event
from fixproof.events import EventType, TraceEvent
from fixproof.models import ModelRole, Report, TestRun
from fixproof.sandbox.executor import CommandResult
from fixproof.trace import read_trace
from tests.fakes.fake_executor import FakeExecutor
from tests.fakes.fake_model import reply_json, reply_tool
from tests.fakes.scenario import (
    Scenario,
    fix_replies,
    make_scenario,
    plan_reply,
    report_reply,
    reproduce_replies,
)
from tests.fakes.settings import make_settings

REQUIRED: dict[EventType, set[str]] = {
    EventType.RUN_STARTED: {
        "repo_url", "ref", "task", "mode", "budget", "models", "sampling", "executor",
    },
    EventType.PHASE_CHANGED: {"from", "to"},
    EventType.REPO_FETCHED: {"resolved_sha", "size_kb"},
    EventType.SANDBOX_OP: {
        "op", "image_in", "image_out", "command", "exit_code", "elapsed_s", "disposable",
    },
    EventType.SNAPSHOT: {"label", "image_id", "tag", "parent_id"},
    EventType.INSTALL_RESULT: {"command", "exit_code", "elapsed_s", "output_tail"},
    EventType.TEST_RUN: {
        "test_run_id", "selector", "counts", "failed_ids", "timed_out", "elapsed_s",
    },
    EventType.PLAN: {"stage", "steps", "understanding"},
    EventType.HYPOTHESES: {"items"},
    EventType.MODEL_CALL: {
        "role", "model", "temperature", "max_tokens", "top_p", "prompt_tokens",
        "completion_tokens", "cost_usd", "elapsed_s", "fallback_from", "has_reasoning",
    },
    EventType.REASONING: {"role", "text"},
    EventType.TOOL_CALL: {"call_id", "tool", "args", "purpose"},
    EventType.TOOL_RESULT: {"call_id", "tool", "ok", "summary", "error", "elapsed_s"},
    EventType.REPRO_STATUS: {"repro_test_id", "created", "fails_before"},
    EventType.VERIFICATION: {"repro_passes", "regressions", "modified_test_files", "label"},
    EventType.ATTEMPT_FINISHED: {"status", "label", "changed_lines"},
    EventType.BUDGET: {"steps_used", "seconds_elapsed", "cost_usd", "limit_hit"},
    EventType.ERROR: {"where", "message", "fatal"},
    EventType.REPORT: {
        "label", "stop_reason", "summary", "root_cause_md", "citations", "changed_lines", "flags",
    },
    EventType.RUN_FINISHED: {"label", "stop_reason", "duration_s", "cost_usd", "patch_available"},
}  # fmt: skip


async def happy(runs: Path) -> Scenario:
    s = make_scenario(runs)
    await s.run()
    return s


async def rediagnosis(runs: Path) -> Scenario:
    partial = "return a + b if a == 2 else 0"
    s = make_scenario(
        runs,
        planner=[plan_reply(), plan_reply(), plan_reply(), report_reply()],
        worker=[
            *reproduce_replies(),
            *fix_replies(new=partial),
            *fix_replies(old=partial, new="return a + b"),
        ],
    )
    await s.run()
    return s


async def setup_failed(runs: Path) -> Scenario:
    executor = FakeExecutor()
    executor.install_ok = False
    s = make_scenario(
        runs,
        executor=executor,
        planner=[plan_reply()],
        worker=[reply_json({"command": "python -m pip install ."}, role=ModelRole.WORKER)],
    )
    await s.run()
    return s


async def stopped_in_tool(runs: Path) -> Scenario:
    executor = FakeExecutor()
    started = asyncio.Event()

    async def slow(command: str, fs: dict[str, bytes]) -> CommandResult:
        started.set()
        await asyncio.sleep(300)
        return CommandResult(stdout="")

    executor.add_rule(r"^sleep", slow)
    s = make_scenario(
        runs,
        executor=executor,
        planner=[plan_reply(), plan_reply()],
        worker=[reply_tool("run_command", command="sleep 300", purpose="wait")],
    )
    task = asyncio.create_task(s.run())
    await asyncio.wait_for(started.wait(), 5)
    s.orchestrator.stop()
    await asyncio.wait_for(task, 10)
    return s


SCENARIOS: dict[str, Callable[[Path], Awaitable[Scenario]]] = {
    "happy": happy,
    "rediagnosis": rediagnosis,
    "setup_failed": setup_failed,
    "stopped_in_tool": stopped_in_tool,
}


@pytest.fixture(params=sorted(SCENARIOS))
async def scenario(request: pytest.FixtureRequest, tmp_runs_dir: Path) -> Scenario:
    return await SCENARIOS[request.param](tmp_runs_dir)


def trace_of(s: Scenario) -> list[TraceEvent]:
    return read_trace(s.run_dir / "trace.jsonl")


async def test_every_event_has_its_contract_fields(scenario: Scenario) -> None:
    for event in trace_of(scenario):
        missing = REQUIRED[event.type] - set(event.data)
        assert not missing, f"{event.type}: missing {missing}"
        assert event.run_id == scenario.bus.run_id
        assert event.replay is False


async def test_sequence_is_strictly_increasing_from_one(scenario: Scenario) -> None:
    trace = trace_of(scenario)
    assert [e.seq for e in trace] == list(range(1, len(trace) + 1))
    assert [e.seq for e in trace] == [e.seq for e in scenario.bus.history]


async def test_run_finished_is_present_once_and_last(scenario: Scenario) -> None:
    types = [e.type for e in trace_of(scenario)]
    assert types[0] is EventType.RUN_STARTED
    assert types[-1] is EventType.RUN_FINISHED
    assert types.count(EventType.RUN_FINISHED) == 1
    assert types.count(EventType.REPORT) == 1


async def test_each_tool_call_has_exactly_one_result(scenario: Scenario) -> None:
    trace = trace_of(scenario)
    calls = Counter(e.data["call_id"] for e in trace if e.type is EventType.TOOL_CALL)
    results = Counter(e.data["call_id"] for e in trace if e.type is EventType.TOOL_RESULT)
    assert calls == results
    assert all(count == 1 for count in calls.values())


async def test_sampling_parameters_are_recorded(scenario: Scenario) -> None:
    sampling = make_settings().sampling()
    trace = trace_of(scenario)
    started = trace[0]
    assert started.data["sampling"] == sampling
    model_calls = [e for e in trace if e.type is EventType.MODEL_CALL]
    assert model_calls
    for event in model_calls:
        assert {k: event.data[k] for k in sampling} == sampling


async def test_plans_are_initial_then_refined(scenario: Scenario) -> None:
    stages = [e.data["stage"] for e in trace_of(scenario) if e.type is EventType.PLAN]
    assert stages and stages[0] == "initial"
    assert set(stages) <= {"initial", "refined"}


async def test_report_only_claims_actions_that_are_in_the_trace(scenario: Scenario) -> None:
    """SC-005: every changed file and every test run in the report has an event."""
    trace = trace_of(scenario)
    report = Report.model_validate_json((scenario.run_dir / "report.json").read_text("utf-8"))
    [report_data] = [e.data for e in trace if e.type is EventType.REPORT]
    assert report_data == report_event(report)

    written = {
        e.data["args"]["path"]
        for e in trace
        if e.type is EventType.TOOL_CALL and e.data["tool"] in ("create_file", "edit_file")
    }
    for change in report.patch.files if report.patch else ():
        assert change.path in written, change.path

    test_runs = {e.data["test_run_id"] for e in trace if e.type is EventType.TEST_RUN}
    evidence = report.evidence
    runs: list[TestRun] = []
    if evidence is not None:
        runs = [evidence.baseline, *evidence.repro_after]
        runs += [r for r in (evidence.repro_before, evidence.regression) if r is not None]
    for test_run in runs:
        assert test_run.id in test_runs, test_run.id

    [finished] = [e for e in trace if e.type is EventType.RUN_FINISHED]
    assert finished.data["label"] == report.label.value
    assert finished.data["stop_reason"] == report.stop_reason.value
    assert finished.data["patch_available"] == (scenario.run_dir / "patch.diff").exists()


async def test_stopped_tool_call_is_closed_as_stopped(tmp_runs_dir: Path) -> None:
    s = await stopped_in_tool(tmp_runs_dir)
    results = [e for e in trace_of(s) if e.type is EventType.TOOL_RESULT]
    assert results[-1].data["error"] == "stopped" and results[-1].data["ok"] is False
