"""Independent verification and the labeling rule (research R8, data-model.md).

The harness, not the model, decides the label:

- **verified**: the reproduction test passes on 3 consecutive runs, every test that passed at
  baseline still passes (flaky tests excluded), no existing test file was modified, and the
  baseline had at least one passing test besides the reproduction test;
- **needs review**: the tests pass, but existing test files were modified or the repository had
  no prior passing tests (so there is no regression evidence);
- **not verified**: anything else.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from dataclasses import dataclass

from fixproof.budget import BudgetTracker
from fixproof.events import EventBus, EventType
from fixproof.models import (
    Evidence,
    FileStatus,
    OutcomeLabel,
    Patch,
    Snapshot,
    TestOutcome,
    TestRun,
)
from fixproof.sandbox.executor import Executor, compute_patch
from fixproof.sandbox.pytest_results import TestRunner

REPRO_RUNS = 3
_RERUN_LIMIT = 50
_LABEL_RANK = {OutcomeLabel.NOT_VERIFIED: 0, OutcomeLabel.NEEDS_REVIEW: 1, OutcomeLabel.VERIFIED: 2}


def label_rank(label: OutcomeLabel) -> int:
    """Return 2 for verified, 1 for needs review, and 0 for not verified."""
    return _LABEL_RANK[label]


def repro_passes(evidence: Evidence) -> list[bool]:
    """Return, per run after the fix, whether the reproduction test passed."""
    test_id = evidence.repro_test_id
    return [
        test_id is not None and run.outcome_of(test_id) is TestOutcome.PASSED
        for run in evidence.repro_after
    ]


def find_regressions(evidence: Evidence) -> list[str]:
    """Return baseline-passing tests (flaky ones excluded) that did not pass after the fix.

    Returns an empty list when there is no regression run yet.
    """
    if evidence.regression is None:
        return []
    expected = evidence.baseline.passed_ids - set(evidence.baseline_flaky)
    return sorted(expected - evidence.regression.passed_ids)


def has_prior_tests(evidence: Evidence) -> bool:
    """Return whether the baseline had a passing test other than the reproduction test.

    Flaky tests still count here: they are excluded only from the regression check.
    """
    return any(node_id != evidence.repro_test_id for node_id in evidence.baseline.passed_ids)


def compute_label(evidence: Evidence) -> OutcomeLabel:
    """Apply the labeling rule to the collected evidence (never to model output)."""
    passes = repro_passes(evidence)
    repro_ok = len(passes) >= REPRO_RUNS and all(passes)
    if not repro_ok or evidence.regression is None or find_regressions(evidence):
        return OutcomeLabel.NOT_VERIFIED
    if evidence.modified_test_files or not has_prior_tests(evidence):
        return OutcomeLabel.NEEDS_REVIEW
    return OutcomeLabel.VERIFIED


@dataclass(frozen=True)
class Verification:
    """Outcome of verifying one candidate fix.

    Attributes:
        label: The harness label.
        evidence: Baseline, reproduction, and after-fix test evidence.
        patch: The candidate patch against the baseline commit.
        snapshot: The verified snapshot.
        regressions: Baseline-passing tests that fail after the fix.
        repro_passes: Result of each reproduction run after the fix.
    """

    label: OutcomeLabel
    evidence: Evidence
    patch: Patch
    snapshot: Snapshot
    regressions: tuple[str, ...]
    repro_passes: tuple[bool, ...]

    def describe(self) -> str:
        """Explain the result in plain text, for the planner's re-diagnosis."""
        ev = self.evidence
        lines = [f"Verification label: {self.label.value}."]
        runs = len(self.repro_passes)
        passed = sum(self.repro_passes)
        lines.append(
            f"Reproduction test {ev.repro_test_id}: passed {passed} of {runs} run(s) "
            f"(needs {REPRO_RUNS} of {REPRO_RUNS})."
        )
        if ev.repro_after and not all(self.repro_passes):
            message = _failure_message(ev.repro_after[-1], ev.repro_test_id)
            lines.append(f"Last reproduction failure: {message}")
            lines.append(f"Output tail:\n{ev.repro_after[-1].output_tail[-1500:]}")
        if self.regressions:
            lines.append("Tests that passed before the change and fail now:")
            for node_id in self.regressions[:10]:
                detail = _failure_message(ev.regression, node_id) if ev.regression else ""
                lines.append(f"- {node_id}: {detail}")
        if ev.modified_test_files:
            lines.append(
                "Existing test files were modified (not allowed for a verified fix): "
                + ", ".join(ev.modified_test_files)
            )
        return "\n".join(lines)


def _failure_message(run: TestRun, node_id: str | None) -> str:
    for result in run.results:
        if result.node_id == node_id:
            return (result.message or result.outcome.value)[:800]
    return "the test did not run (it was not collected)"


async def verify_fix(
    *,
    executor: Executor,
    tests: TestRunner,
    snapshot: Snapshot,
    evidence: Evidence,
    repro_files: Mapping[str, bytes],
    bus: EventBus,
    attempt_id: str | None = None,
    budget: BudgetTracker | None = None,
) -> Verification:
    """Verify a candidate fix independently of the model.

    Steps: run the reproduction test up to 3 times (stopping at the first failure), compute the
    patch and the modified test files, run the full suite, and re-run apparent regressions once
    to rule out flaky tests. Publishes one ``verification`` event.

    Args:
        executor: The isolated environment.
        tests: Shared test runner (publishes ``test_run`` events).
        snapshot: The candidate fix.
        evidence: Baseline and reproduction evidence; it is copied, never changed.
        repro_files: Content of the reproduction test files when the reproduction was confirmed.
            Any later change to them counts as a modified test file.
        bus: The run's event bus.
        attempt_id: The attempt being verified.
        budget: Checked (time and cost only) before each test run.

    Returns:
        The verification result.

    Raises:
        ValueError: If the evidence has no reproduction test.
    """
    if evidence.repro_test_id is None:
        raise ValueError("cannot verify without a reproduction test")
    ev = evidence.model_copy(deep=True)
    ev.repro_after = []
    ev.regression = None
    test_id = ev.repro_test_id
    assert test_id is not None
    for _ in range(REPRO_RUNS):
        _check(budget)
        run = await tests.run(snapshot, shlex.quote(test_id), attempt_id=attempt_id)
        ev.repro_after.append(run)
        if run.outcome_of(test_id) is not TestOutcome.PASSED:
            break
    _check(budget)
    patch = await compute_patch(executor, snapshot)
    ev.modified_test_files = await _modified_test_files(executor, snapshot, patch, repro_files)
    passes = repro_passes(ev)
    flaky: list[str] = []
    if len(passes) == REPRO_RUNS and all(passes):
        _check(budget)
        ev.regression = await tests.run(snapshot, None, attempt_id=attempt_id)
        candidates = find_regressions(ev)
        if candidates and len(candidates) <= _RERUN_LIMIT:
            _check(budget)
            selector = " ".join(shlex.quote(node_id) for node_id in candidates)
            rerun = await tests.run(snapshot, selector, attempt_id=attempt_id)
            flaky = [c for c in candidates if rerun.outcome_of(c) is TestOutcome.PASSED]
            ev.baseline_flaky = sorted(set(ev.baseline_flaky) | set(flaky))
    label = compute_label(ev)
    regressions = find_regressions(ev)
    bus.publish(
        EventType.VERIFICATION,
        {
            "repro_test_id": test_id,
            "repro_passes": passes,
            "regressions": regressions[:50],
            "modified_test_files": ev.modified_test_files,
            "flaky": flaky,
            "label": label.value,
        },
        attempt_id=attempt_id,
    )
    return Verification(
        label=label,
        evidence=ev,
        patch=patch,
        snapshot=snapshot,
        regressions=tuple(regressions),
        repro_passes=tuple(passes),
    )


def _check(budget: BudgetTracker | None) -> None:
    if budget is not None:
        budget.check(steps=False)


async def _modified_test_files(
    executor: Executor, snapshot: Snapshot, patch: Patch, repro_files: Mapping[str, bytes]
) -> list[str]:
    """Return existing test files that changed (since the baseline, or since reproduction)."""
    changed = {
        change.path
        for change in patch.files
        if change.is_test_file and change.status in (FileStatus.MODIFIED, FileStatus.DELETED)
    }
    for path, original in repro_files.items():
        try:
            current: bytes | None = await executor.read_file(snapshot, path)
        except FileNotFoundError:
            current = None
        if current != original:
            changed.add(path)
    return sorted(changed)
