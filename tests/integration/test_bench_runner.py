"""The benchmark runner (FR-023, SC-001, SC-002, SC-004, SC-007) with fakes.

The calc fake gets a hidden reference test (``add(3, 4) == 7``) that only the benchmark's
after-run check may add, in a fresh environment.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from fixproof import cli
from fixproof.bench.runner import (
    BenchRow,
    BenchRunner,
    BenchServices,
    HiddenResult,
    RecheckResult,
    load_results,
    paired_rows,
    percentile,
    render_summary,
    summarize,
)
from fixproof.bench.tasks import load_benchmark_tasks
from fixproof.cli import Factories, app
from fixproof.config import Settings
from fixproof.models import ModelRole, OutcomeLabel, RunMode, StopReason, TestCaseResult
from fixproof.repo.patches import changed_files, drop_files
from tests.fakes.calc_repo import CALC_FILES, EXISTING_ID, REPO_URL, calc_behavior, selected
from tests.fakes.fake_executor import FakeExecutor, outcome
from tests.fakes.fake_github import DEFAULT_SHA, FakeGitHub
from tests.fakes.fake_model import FakeModelClient
from tests.fakes.git_apply import git_apply
from tests.fakes.parallel import BranchScripts, parallel_planner
from tests.fakes.scenario import fix_replies, happy_planner, happy_worker, reproduce_replies
from tests.fakes.settings import make_settings

TASK_ID = "acme__calc-7"
HIDDEN_PATH = "tests/test_hidden.py"
HIDDEN_ID = f"{HIDDEN_PATH}::test_add_hidden"
HIDDEN_TEST = "from calc.core import add\n\n\ndef test_add_hidden():\n    assert add(3, 4) == 7\n"
HIDDEN_PATCH = (
    f"diff --git a/{HIDDEN_PATH} b/{HIDDEN_PATH}\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    f"+++ b/{HIDDEN_PATH}\n"
    "@@ -0,0 +1,5 @@\n" + "".join(f"+{line}\n" for line in HIDDEN_TEST.splitlines())
)
TASKS_TOML = f"""
[[tasks]]
id = "{TASK_ID}"
repo_url = "{REPO_URL}"
base_commit = "{DEFAULT_SHA}"
python = "3.12"
hidden_fail_to_pass = ["{HIDDEN_ID}"]
hidden_pass_to_pass = ["{EXISTING_ID}"]
hidden_test_patch = "hidden/{TASK_ID}.patch"

[tasks.task]
kind = "description"
value = "add() returns the wrong result: add(2, 3) returns -1 instead of 5."
"""
OVERFIT = "return a + b if (a, b) == (2, 3) else a - b"
runner = CliRunner()

Script = tuple[list[Any], list[Any]]


def bench_behavior(fs: Mapping[str, bytes], selector: str | None) -> list[TestCaseResult]:
    """The calc tests plus the hidden reference test, when its file exists."""
    results = calc_behavior(fs, selector)
    if HIDDEN_PATH in fs and selected(HIDDEN_ID, selector):
        namespace: dict[str, Any] = {}
        exec(fs["calc/core.py"].decode(), namespace)
        ok = namespace["add"](3, 4) == 7
        results.append(outcome(HIDDEN_ID, "passed" if ok else "failed", None if ok else "-1"))
    return results


class Fakes:
    """Fresh fakes for every run and every check, with the model scripts used in order."""

    def __init__(self, *scripts: Script) -> None:
        self.scripts = list(scripts)
        self.models: list[FakeModelClient] = []
        self.executors: list[FakeExecutor] = []

    def model(self, settings: Settings) -> FakeModelClient:
        planner, worker = self.scripts[len(self.models)]
        model = FakeModelClient()
        model.script(ModelRole.PLANNER, *planner).script(ModelRole.WORKER, *worker)
        self.models.append(model)
        return model

    def executor(self, settings: Settings, on_event: Any) -> FakeExecutor:
        executor = FakeExecutor()
        executor.test_behavior = bench_behavior
        executor.add_rule(r"^git apply", git_apply)
        self.executors.append(executor)
        return executor

    def repo_source(self, settings: Settings) -> FakeGitHub:
        return FakeGitHub(CALC_FILES)

    def services(self) -> BenchServices:
        return BenchServices(model=self.model, executor=self.executor, repo_source=self.repo_source)


def write_tasks(folder: Path) -> Path:
    (folder / "hidden").mkdir(parents=True, exist_ok=True)
    (folder / "hidden" / f"{TASK_ID}.patch").write_text(HIDDEN_PATCH, encoding="utf-8")
    tasks_file = folder / "tasks.toml"
    tasks_file.write_text(TASKS_TOML, encoding="utf-8")
    return tasks_file


async def run_bench(tmp_path: Path, fakes: Fakes, **options: Any) -> Any:
    tasks_file = write_tasks(tmp_path)
    bench = BenchRunner(
        settings=make_settings(),
        services=fakes.services(),
        out_dir=tmp_path / "out",
        tasks_file=tasks_file,
    )
    return await bench.run(load_benchmark_tasks(tasks_file), **options)


# -- running the benchmark -------------------------------------------------------------------


async def test_a_verified_fix_is_rechecked_and_agrees_with_the_hidden_tests(
    tmp_path: Path,
) -> None:
    results = await run_bench(tmp_path, Fakes((happy_planner(), happy_worker())))
    [row] = results.rows
    assert (row.task_id, row.mode, row.label) == (TASK_ID, RunMode.SINGLE, OutcomeLabel.VERIFIED)
    assert row.recheck is not None and row.recheck.passed, row.recheck
    assert row.hidden is not None and row.hidden.passed and row.hidden.fails_before_fix
    assert row.hidden.fail_to_pass == {HIDDEN_ID: "passed"}
    assert row.hidden.pass_to_pass_checked == 1 and row.hidden.pass_to_pass_broken == []
    assert row.agrees is True and row.check_error is None
    assert row.duration_s >= 0 and row.cost_usd > 0 and row.max_seconds == 900

    saved = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert saved["rows"][0]["task_id"] == TASK_ID and saved["rows"][0]["label"] == "verified"
    assert (tmp_path / "out" / "runs" / row.run_id / "report.json").is_file()
    assert (tmp_path / "out" / "checks" / row.run_id / "trace.jsonl").is_file()
    summary = (tmp_path / "out" / "summary.md").read_text(encoding="utf-8")
    assert "| single | 1 | 1 (100%) |" in summary


async def test_hidden_tests_never_reach_the_model_or_the_agents_sandbox(tmp_path: Path) -> None:
    fakes = Fakes((happy_planner(), happy_worker()))
    await run_bench(tmp_path, fakes)
    shown = "\n".join(request.text() for model in fakes.models for request in model.requests)
    assert "test_add_hidden" not in shown and "add(3, 4)" not in shown and HIDDEN_PATH not in shown
    agent, check = fakes.executors
    assert not any(HIDDEN_PATH in files for files in agent._fs.values())
    assert any(HIDDEN_PATH in files for files in check._fs.values())
    trace = next((tmp_path / "out" / "runs").glob("*/trace.jsonl")).read_text(encoding="utf-8")
    assert "test_add_hidden" not in trace


async def test_an_overfitted_fix_is_verified_but_disagrees_with_the_hidden_tests(
    tmp_path: Path,
) -> None:
    worker = [*reproduce_replies(), *fix_replies(new=OVERFIT)]
    results = await run_bench(tmp_path, Fakes((happy_planner(), worker)))
    [row] = results.rows
    assert row.label is OutcomeLabel.VERIFIED
    assert row.recheck is not None and row.recheck.passed
    assert row.hidden is not None and not row.hidden.passed
    assert row.hidden.fail_to_pass == {HIDDEN_ID: "failed"}
    assert row.agrees is False


async def test_compare_single_runs_both_modes_and_pairs_them(tmp_path: Path) -> None:
    fakes = Fakes(
        (parallel_planner(), BranchScripts().worker_queue()), (happy_planner(), happy_worker())
    )
    results = await run_bench(tmp_path, fakes, parallel=3, compare_single=True)
    assert [(r.task_id, r.mode) for r in results.rows] == [
        (TASK_ID, RunMode.PARALLEL),
        (TASK_ID, RunMode.SINGLE),
    ]
    [pair] = paired_rows(results.rows)
    assert (pair.task_id, pair.single, pair.parallel) == (
        TASK_ID,
        OutcomeLabel.VERIFIED,
        OutcomeLabel.VERIFIED,
    )
    assert "## Single path versus parallel hypotheses" in render_summary(results)


def test_compare_single_needs_parallel_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="--parallel"):
        BenchRunner(
            settings=make_settings(),
            services=Fakes().services(),
            out_dir=tmp_path / "out",
            tasks_file=write_tasks(tmp_path),
        ).check_options(parallel=1, compare_single=True)


# -- summary math ----------------------------------------------------------------------------

RECHECK_OK = RecheckResult(passed=True, label=OutcomeLabel.VERIFIED)
RECHECK_FAILED = RecheckResult(passed=False, label=OutcomeLabel.NOT_VERIFIED, detail="flaky")
HIDDEN_OK = HiddenResult(passed=True, fail_to_pass={HIDDEN_ID: "passed"}, fails_before_fix=True)


def make_row(
    label: OutcomeLabel,
    duration_s: float,
    *,
    mode: RunMode = RunMode.SINGLE,
    task_id: str = "t",
    recheck: RecheckResult | None = None,
    agrees: bool | None = None,
) -> BenchRow:
    return BenchRow(
        task_id=task_id,
        mode=mode,
        run_id="run-20261014-000000-abcdef",
        label=label,
        stop_reason=StopReason.COMPLETED,
        duration_s=duration_s,
        cost_usd=0.1,
        max_seconds=900,
        recheck=recheck,
        hidden=HIDDEN_OK if agrees is not None else None,
        agrees=agrees,
    )


def test_summary_math() -> None:
    rows = [
        make_row(OutcomeLabel.VERIFIED, 60, recheck=RECHECK_OK, agrees=True),
        make_row(OutcomeLabel.VERIFIED, 120, recheck=RECHECK_FAILED, agrees=False),
        make_row(OutcomeLabel.NEEDS_REVIEW, 600, agrees=True),
        make_row(OutcomeLabel.NOT_VERIFIED, 950),
        make_row(OutcomeLabel.NOT_VERIFIED, 2000, agrees=True),
        make_row(OutcomeLabel.VERIFIED, 30, mode=RunMode.PARALLEL),
    ]
    s = summarize(rows, RunMode.SINGLE)
    assert (s.tasks, s.verified, s.needs_review, s.not_verified) == (5, 2, 1, 2)
    assert s.verified_rate == pytest.approx(0.4)
    assert (s.rechecked, s.recheck_failures) == (2, 1)
    assert (s.hidden_checked, s.hidden_agree) == (4, 3)
    assert (s.p50_s, s.p90_s) == (600, 2000)
    assert s.within_15_min == pytest.approx(0.6)
    assert s.within_max == pytest.approx(0.8)  # 950 s is within 900 s plus the reporting grace
    assert s.cost_usd == pytest.approx(0.5)


def test_percentile_uses_the_nearest_rank() -> None:
    assert percentile([], 50) == 0.0
    assert percentile([7.0], 90) == 7.0
    assert percentile([4.0, 1.0, 3.0, 2.0], 50) == 2.0
    assert percentile([4.0, 1.0, 3.0, 2.0], 90) == 4.0


def test_pairs_name_tasks_only_parallel_verified() -> None:
    rows = [
        make_row(OutcomeLabel.VERIFIED, 60, mode=RunMode.PARALLEL, task_id="a"),
        make_row(OutcomeLabel.NOT_VERIFIED, 60, mode=RunMode.SINGLE, task_id="a"),
        make_row(OutcomeLabel.VERIFIED, 60, mode=RunMode.PARALLEL, task_id="b"),
        make_row(OutcomeLabel.VERIFIED, 60, mode=RunMode.SINGLE, task_id="b"),
        make_row(OutcomeLabel.VERIFIED, 60, mode=RunMode.PARALLEL, task_id="c"),  # no pair
    ]
    pairs = paired_rows(rows)
    assert [(p.task_id, p.single, p.parallel) for p in pairs] == [
        ("a", OutcomeLabel.NOT_VERIFIED, OutcomeLabel.VERIFIED),
        ("b", OutcomeLabel.VERIFIED, OutcomeLabel.VERIFIED),
    ]


# -- diff helpers ----------------------------------------------------------------------------

AGENT_DIFF = (
    "diff --git a/calc/core.py b/calc/core.py\n--- a/calc/core.py\n+++ b/calc/core.py\n"
    "@@ -1 +1 @@\n-x\n+y\n"
    f"diff --git a/{HIDDEN_PATH} b/{HIDDEN_PATH}\nnew file mode 100644\n--- /dev/null\n"
    f"+++ b/{HIDDEN_PATH}\n@@ -0,0 +1 @@\n+z\n"
)


def test_changed_files_and_drop_files() -> None:
    assert changed_files(AGENT_DIFF) == ["calc/core.py", HIDDEN_PATH]
    kept = drop_files(AGENT_DIFF, {HIDDEN_PATH})
    assert changed_files(kept) == ["calc/core.py"] and kept.endswith("+y\n")
    assert drop_files(AGENT_DIFF, {"calc/core.py", HIDDEN_PATH}) == ""


# -- CLI -------------------------------------------------------------------------------------


def use_bench_fakes(monkeypatch: pytest.MonkeyPatch, fakes: Fakes) -> None:
    settings = make_settings()
    monkeypatch.setattr(
        cli,
        "factories",
        Factories(
            settings=lambda: settings,
            model=fakes.model,
            executor=fakes.executor,
            repo_source=fakes.repo_source,
        ),
    )


def test_bench_run_and_report_from_the_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    use_bench_fakes(monkeypatch, Fakes((happy_planner(), happy_worker())))
    tasks_file = write_tasks(tmp_path)
    out = tmp_path / "results"
    result = runner.invoke(app, ["bench", "run", "--tasks", str(tasks_file), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert f"{TASK_ID} (single): verified" in result.stdout
    assert load_results(out).rows[0].label is OutcomeLabel.VERIFIED

    report = runner.invoke(app, ["bench", "report", str(out)])
    assert report.exit_code == 0, report.output
    assert "| single | 1 | 1 (100%) |" in report.stdout
    as_json = runner.invoke(app, ["bench", "report", str(out), "--json"])
    assert json.loads(as_json.stdout)["summaries"][0]["verified"] == 1


def test_bench_cli_rejects_bad_input(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    use_bench_fakes(monkeypatch, Fakes())
    tasks_file = write_tasks(tmp_path)
    unknown = runner.invoke(app, ["bench", "run", "--tasks", str(tasks_file), "--only", "nope"])
    assert unknown.exit_code == 2 and "nope" in unknown.stderr
    compare = runner.invoke(app, ["bench", "run", "--tasks", str(tasks_file), "--compare-single"])
    assert compare.exit_code == 2 and "--parallel" in compare.stderr
    missing = runner.invoke(app, ["bench", "report", str(tmp_path / "missing")])
    assert missing.exit_code == 2
