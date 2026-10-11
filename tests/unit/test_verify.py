"""The harness labeling rule (data-model.md) and independent verification on the fake sandbox."""

from __future__ import annotations

import itertools
from collections.abc import Mapping
from pathlib import Path

import pytest

from fixproof.agent.verify import (
    compute_label,
    find_regressions,
    has_prior_tests,
    verify_fix,
)
from fixproof.budget import BudgetExceeded, BudgetTracker
from fixproof.events import EventBus, EventType
from fixproof.models import (
    Budget,
    Evidence,
    OutcomeLabel,
    Snapshot,
    TestCaseResult,
    TestOutcome,
    TestRun,
)
from fixproof.sandbox.executor import git_baseline_command
from fixproof.sandbox.pytest_results import TestRunner
from tests.fakes.calc_repo import (
    CALC_FILES,
    EXISTING_ID,
    REPRO_ID,
    REPRO_PATH,
    REPRO_TEST,
    calc_behavior,
)
from tests.fakes.fake_executor import FakeExecutor

OTHER = "tests/test_core.py::test_other"


def run(run_id: str, outcomes: Mapping[str, str]) -> TestRun:
    results = tuple(TestCaseResult(node_id=n, outcome=TestOutcome(o)) for n, o in outcomes.items())
    failed = any(o in ("failed", "error") for o in outcomes.values())
    return TestRun(id=run_id, snapshot_id="img", results=results, exit_code=int(failed))


def evidence(**overrides: object) -> Evidence:
    ev = Evidence(
        baseline=run("tr-1", {EXISTING_ID: "passed", OTHER: "passed"}),
        repro_test_id=REPRO_ID,
        repro_created=True,
        repro_before=run("tr-2", {REPRO_ID: "failed"}),
        repro_after=[run(f"tr-{i}", {REPRO_ID: "passed"}) for i in (3, 4, 5)],
        regression=run("tr-6", {EXISTING_ID: "passed", OTHER: "passed", REPRO_ID: "passed"}),
    )
    for key, value in overrides.items():
        setattr(ev, key, value)
    return ev


def test_verified_when_every_condition_holds() -> None:
    assert compute_label(evidence()) is OutcomeLabel.VERIFIED


def test_needs_review_when_an_existing_test_file_was_modified() -> None:
    ev = evidence(modified_test_files=["tests/test_core.py"])
    assert compute_label(ev) is OutcomeLabel.NEEDS_REVIEW


def test_needs_review_when_the_repository_had_no_prior_tests() -> None:
    ev = evidence(
        baseline=run("tr-1", {}),
        regression=run("tr-6", {REPRO_ID: "passed"}),
    )
    assert not has_prior_tests(ev)
    assert compute_label(ev) is OutcomeLabel.NEEDS_REVIEW


def test_needs_review_when_no_prior_test_passed_at_baseline() -> None:
    ev = evidence(
        baseline=run("tr-1", {EXISTING_ID: "failed"}),
        regression=run("tr-6", {EXISTING_ID: "failed", REPRO_ID: "passed"}),
    )
    assert compute_label(ev) is OutcomeLabel.NEEDS_REVIEW


def test_not_verified_on_a_regression() -> None:
    ev = evidence(
        regression=run("tr-6", {EXISTING_ID: "passed", OTHER: "failed", REPRO_ID: "passed"})
    )
    assert find_regressions(ev) == [OTHER]
    assert compute_label(ev) is OutcomeLabel.NOT_VERIFIED


def test_a_baseline_test_missing_after_the_fix_is_a_regression() -> None:
    ev = evidence(regression=run("tr-6", {EXISTING_ID: "passed", REPRO_ID: "passed"}))
    assert find_regressions(ev) == [OTHER]
    assert compute_label(ev) is OutcomeLabel.NOT_VERIFIED


def test_not_verified_when_the_reproduction_passes_only_two_of_three_times() -> None:
    after = [
        run("tr-3", {REPRO_ID: "passed"}),
        run("tr-4", {REPRO_ID: "failed"}),
        run("tr-5", {REPRO_ID: "passed"}),
    ]
    assert compute_label(evidence(repro_after=after)) is OutcomeLabel.NOT_VERIFIED
    assert compute_label(evidence(repro_after=after[:2])) is OutcomeLabel.NOT_VERIFIED


def test_not_verified_without_regression_run_or_reproduction_test() -> None:
    assert compute_label(evidence(regression=None)) is OutcomeLabel.NOT_VERIFIED
    assert compute_label(evidence(repro_test_id=None)) is OutcomeLabel.NOT_VERIFIED


def test_baseline_flaky_tests_are_excluded_from_the_regression_check() -> None:
    ev = evidence(
        baseline_flaky=[OTHER],
        regression=run("tr-6", {EXISTING_ID: "passed", OTHER: "failed", REPRO_ID: "passed"}),
    )
    assert find_regressions(ev) == []
    assert compute_label(ev) is OutcomeLabel.VERIFIED


# -- verify_fix on the fake sandbox --------------------------------------------------------


class Repo:
    """Installed calc repository with its reproduction test, ready for fixes."""

    def __init__(self, executor: FakeExecutor, installed: Snapshot, repro: Snapshot) -> None:
        self.executor, self.installed, self.repro = executor, installed, repro
        self.bus = EventBus("run-20261010-000000-abcdef")
        self.tests = TestRunner(executor, timeout_s=60, bus=self.bus)

    async def evidence(self) -> Evidence:
        baseline = await self.tests.run(self.installed)
        before = await self.tests.run(self.repro, REPRO_ID)
        return Evidence(
            baseline=baseline, repro_test_id=REPRO_ID, repro_created=True, repro_before=before
        )

    async def change(self, files: Mapping[str, str]) -> Snapshot:
        return await self.executor.write_files(
            self.repro, {path: text.encode() for path, text in files.items()}
        )


async def make_repo() -> Repo:
    executor = FakeExecutor(CALC_FILES)
    executor.test_behavior = calc_behavior
    source = await executor.prepare_repo(Path("no-tarball.tgz"), "python:3.12")
    _, installed = await executor.run(source, git_baseline_command(), timeout_s=60, mutate=True)
    repro = await executor.write_files(installed, {REPRO_PATH: REPRO_TEST.encode()})
    return Repo(executor, installed, repro)


FIXED_CORE = CALC_FILES["calc/core.py"].replace("a - b", "a + b")


async def test_verify_fix_labels_a_real_fix_verified() -> None:
    repo = await make_repo()
    fixed = await repo.change({"calc/core.py": FIXED_CORE})
    result = await verify_fix(
        executor=repo.executor,
        tests=repo.tests,
        snapshot=fixed,
        evidence=await repo.evidence(),
        repro_files={REPRO_PATH: REPRO_TEST.encode()},
        bus=repo.bus,
        attempt_id="a1",
    )
    assert result.label is OutcomeLabel.VERIFIED
    assert result.repro_passes == (True, True, True)
    assert len(result.evidence.repro_after) == 3
    assert result.evidence.regression is not None
    assert {f.path for f in result.patch.files} == {"calc/core.py", REPRO_PATH}
    [event] = [e for e in repo.bus.history if e.type is EventType.VERIFICATION]
    assert event.attempt_id == "a1"
    assert event.data["label"] == "verified"
    assert event.data["repro_passes"] == [True, True, True]
    assert event.data["regressions"] == [] and event.data["modified_test_files"] == []


async def test_verify_fix_stops_at_the_first_failed_reproduction_run() -> None:
    repo = await make_repo()
    result = await verify_fix(
        executor=repo.executor,
        tests=repo.tests,
        snapshot=repo.repro,
        evidence=await repo.evidence(),
        repro_files={},
        bus=repo.bus,
    )
    assert result.label is OutcomeLabel.NOT_VERIFIED
    assert result.repro_passes == (False,)
    assert result.evidence.regression is None
    assert "passed 0 of 1" in result.describe()


async def test_verify_fix_finds_regressions() -> None:
    repo = await make_repo()
    only_for_two = CALC_FILES["calc/core.py"].replace("a - b", "a + b if a == 2 else 0")
    broken = await repo.change({"calc/core.py": only_for_two})
    result = await verify_fix(
        executor=repo.executor,
        tests=repo.tests,
        snapshot=broken,
        evidence=await repo.evidence(),
        repro_files={},
        bus=repo.bus,
    )
    assert result.label is OutcomeLabel.NOT_VERIFIED
    assert result.regressions == (EXISTING_ID,)
    assert EXISTING_ID in result.describe()


async def test_verify_fix_caps_the_label_when_an_existing_test_changed() -> None:
    repo = await make_repo()
    weakened = CALC_FILES["tests/test_core.py"].replace("== 5", "is not None")
    fixed = await repo.change({"calc/core.py": FIXED_CORE, "tests/test_core.py": weakened})
    result = await verify_fix(
        executor=repo.executor,
        tests=repo.tests,
        snapshot=fixed,
        evidence=await repo.evidence(),
        repro_files={},
        bus=repo.bus,
    )
    assert result.evidence.modified_test_files == ["tests/test_core.py"]
    assert result.label is OutcomeLabel.NEEDS_REVIEW


async def test_verify_fix_detects_a_changed_reproduction_test() -> None:
    repo = await make_repo()
    tampered = REPRO_TEST + "\n# edited after the reproduction was confirmed\n"
    fixed = await repo.change({"calc/core.py": FIXED_CORE, REPRO_PATH: tampered})
    result = await verify_fix(
        executor=repo.executor,
        tests=repo.tests,
        snapshot=fixed,
        evidence=await repo.evidence(),
        repro_files={REPRO_PATH: REPRO_TEST.encode()},
        bus=repo.bus,
    )
    assert result.evidence.modified_test_files == [REPRO_PATH]
    assert result.label is OutcomeLabel.NEEDS_REVIEW


async def test_verify_fix_reruns_apparent_regressions_to_rule_out_flakes() -> None:
    repo = await make_repo()
    full_suite_runs = itertools.count(1)

    def flaky(fs: Mapping[str, bytes], selector: str | None) -> list[TestCaseResult]:
        results = calc_behavior(fs, selector)
        if selector is None and next(full_suite_runs) == 2:  # the regression run after the fix
            return [
                r.model_copy(update={"outcome": TestOutcome.FAILED})
                if r.node_id == EXISTING_ID
                else r
                for r in results
            ]
        return results

    repo.executor.test_behavior = flaky
    fixed = await repo.change({"calc/core.py": FIXED_CORE})
    result = await verify_fix(
        executor=repo.executor,
        tests=repo.tests,
        snapshot=fixed,
        evidence=await repo.evidence(),
        repro_files={},
        bus=repo.bus,
    )
    assert result.label is OutcomeLabel.VERIFIED
    assert EXISTING_ID in result.evidence.baseline_flaky
    [event] = [e for e in repo.bus.history if e.type is EventType.VERIFICATION]
    assert event.data["flaky"] == [EXISTING_ID]


async def test_verify_fix_checks_the_time_budget() -> None:
    repo = await make_repo()
    now = [0.0]
    tracker = BudgetTracker(
        Budget(max_steps=5, max_seconds=60, max_cost_usd=1.0), clock=lambda: now[0]
    )
    now[0] = 61.0
    with pytest.raises(BudgetExceeded):
        await verify_fix(
            executor=repo.executor,
            tests=repo.tests,
            snapshot=repo.repro,
            evidence=await repo.evidence(),
            repro_files={},
            bus=repo.bus,
            budget=tracker,
        )


async def test_verify_fix_requires_a_reproduction_test() -> None:
    repo = await make_repo()
    ev = await repo.evidence()
    ev.repro_test_id = None
    with pytest.raises(ValueError):
        await verify_fix(
            executor=repo.executor,
            tests=repo.tests,
            snapshot=repo.repro,
            evidence=ev,
            repro_files={},
            bus=repo.bus,
        )
