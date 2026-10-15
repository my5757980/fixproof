"""Benchmark runner (FR-023): run every task, re-check verified fixes, and measure agreement.

The agent sees only the task text and the repository at the task's base commit. After a run
ends, a fresh environment is set up with the run's own install commands, and there:

- a **verified** fix is re-checked with the same harness rule (SC-002);
- the task's hidden reference tests (added by the official test patch, which is never shown to
  the agent or put into its sandbox) run before and after the fix, to see whether they agree
  with the label.

Results go to ``<out>/results.json`` (rewritten after every run) and ``<out>/summary.md``; the
runs' own folders go to ``<out>/runs/`` and the check traces to ``<out>/checks/``.
"""

from __future__ import annotations

import math
import shlex
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fixproof.agent.orchestrator import (
    GIT_TIMEOUT_S,
    MAX_TARBALL_BYTES,
    Orchestrator,
    RunRequest,
    new_event_bus,
)
from fixproof.agent.verify import verify_fix
from fixproof.config import Settings
from fixproof.events import EventBus, EventType
from fixproof.llm.client import ModelClient
from fixproof.models import (
    BenchmarkTask,
    Budget,
    Evidence,
    FileStatus,
    OutcomeLabel,
    Report,
    Run,
    RunMode,
    Snapshot,
    StopReason,
    TestOutcome,
    TestRun,
    utc_now,
)
from fixproof.repo.github import GitHubError, RepoSource, parse_repo_url
from fixproof.repo.patches import changed_files, drop_files
from fixproof.sandbox.executor import Executor, git_baseline_command
from fixproof.sandbox.pytest_results import TestRunner
from fixproof.tools.tavily import TavilySearch
from fixproof.trace import Redactor, TraceWriter, read_trace

EventCallback = Callable[[EventType, dict[str, Any]], None]

TIME_TARGET_S = 15 * 60  # SC-004: 90% of runs reach an outcome within 15 minutes
REPORT_GRACE_S = 60  # a stopped run still writes its report after the time budget runs out
PATCH_FILE = ".fixproof-bench.patch"
_MODE_ORDER = (RunMode.SINGLE, RunMode.PARALLEL)
_STRICT = ConfigDict(extra="forbid")


class CheckError(RuntimeError):
    """The after-run check could not be carried out (this is not a verdict on the fix)."""


class RecheckResult(BaseModel):
    """A verified fix's evidence, re-run in a fresh environment (SC-002)."""

    model_config = _STRICT

    passed: bool
    label: OutcomeLabel
    detail: str = ""


class HiddenResult(BaseModel):
    """The task's hidden reference tests, run without and then with the fix."""

    model_config = _STRICT

    passed: bool
    fail_to_pass: dict[str, str]
    fails_before_fix: bool
    pass_to_pass_checked: int = 0
    pass_to_pass_broken: list[str] = Field(default_factory=list)


class BenchRow(BaseModel):
    """One benchmark run and its checks."""

    model_config = _STRICT

    task_id: str
    mode: RunMode
    run_id: str
    label: OutcomeLabel
    stop_reason: StopReason
    duration_s: float
    cost_usd: float
    max_seconds: int
    patch_lines: int = 0
    recheck: RecheckResult | None = None
    hidden: HiddenResult | None = None
    agrees: bool | None = None  # the hidden tests pass exactly when the label is verified
    check_error: str | None = None


class BenchSummary(BaseModel):
    """The numbers of one mode (SC-001, SC-002, SC-004)."""

    model_config = _STRICT

    mode: RunMode
    tasks: int
    verified: int
    needs_review: int
    not_verified: int
    verified_rate: float
    rechecked: int
    recheck_failures: int
    hidden_checked: int
    hidden_agree: int
    p50_s: float
    p90_s: float
    within_15_min: float
    within_max: float
    cost_usd: float


class PairedRow(BaseModel):
    """One task's single-path and parallel labels, with the same budget (SC-007)."""

    model_config = _STRICT

    task_id: str
    single: OutcomeLabel
    parallel: OutcomeLabel


class BenchResults(BaseModel):
    """Everything ``results.json`` holds."""

    model_config = _STRICT

    version: Literal[1] = 1
    created_at: datetime
    tasks_file: str
    executor: str
    models: dict[str, str]
    budget: Budget
    parallel: int
    compare_single: bool
    dev_only: bool  # not Nebius Token Factory with Token Factory Sandboxes
    platform_note: str | None = None  # what the setup was instead (Settings.platform_note)
    rows: list[BenchRow] = Field(default_factory=list)


def _no_web_search(settings: Settings) -> TavilySearch | None:
    return None


@dataclass(frozen=True)
class BenchServices:
    """How the runner builds the services of each run (the CLI passes its factories)."""

    model: Callable[[Settings], ModelClient]
    executor: Callable[[Settings, EventCallback], Executor]
    repo_source: Callable[[Settings], RepoSource]
    web_search: Callable[[Settings], TavilySearch | None] = _no_web_search


class BenchRunner:
    """Run benchmark tasks through the orchestrator and check every result independently.

    Args:
        settings: Configuration (models, executor, secrets to redact).
        services: Builders of each run's model client, executor, and GitHub source.
        out_dir: The results folder.
        tasks_file: The task file; hidden test patches are read relative to it.
        budget: Limits of each run (the CLI budget by default).
        on_progress: Receives one line per finished run.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        services: BenchServices,
        out_dir: Path,
        tasks_file: Path,
        budget: Budget | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        self._settings = settings
        self._services = services
        self._out_dir = out_dir
        self._runs_dir = out_dir / "runs"
        self._checks_dir = out_dir / "checks"
        self._tasks_file = tasks_file
        self._budget = budget or settings.budget_cli()
        self._on_progress = on_progress or (lambda line: None)

    @staticmethod
    def check_options(*, parallel: int, compare_single: bool) -> None:
        """Validate the run options.

        Raises:
            ValueError: If ``parallel`` is not 1-3, or single-path runs are compared with
                single-path runs.
        """
        if not 1 <= parallel <= 3:
            raise ValueError("--parallel must be 1, 2, or 3.")
        if compare_single and parallel < 2:
            raise ValueError("--compare-single needs --parallel 2 or 3 (it adds single-path runs).")

    async def run(
        self, tasks: Sequence[BenchmarkTask], *, parallel: int = 1, compare_single: bool = False
    ) -> BenchResults:
        """Run every task (in both modes with ``compare_single``) and write the results.

        Raises:
            ValueError: If the options are invalid (see ``check_options``).
        """
        self.check_options(parallel=parallel, compare_single=compare_single)
        if compare_single:
            modes = [RunMode.PARALLEL, RunMode.SINGLE]
        else:
            modes = [RunMode.PARALLEL if parallel > 1 else RunMode.SINGLE]
        settings = self._settings
        results = BenchResults(
            created_at=utc_now(),
            tasks_file=self._tasks_file.as_posix(),
            executor=settings.executor,
            models=settings.models_by_role(),
            budget=self._budget,
            parallel=parallel,
            compare_single=compare_single,
            dev_only=settings.platform_note() is not None,
            platform_note=settings.platform_note(),
        )
        total = len(tasks) * len(modes)
        for task in tasks:
            for mode in modes:
                row = await self._run_task(task, mode, parallel)
                results.rows.append(row)
                write_results(self._out_dir, results)
                self._on_progress(f"[{len(results.rows)}/{total}] {describe_row(row)}")
        write_results(self._out_dir, results)
        return results

    async def _run_task(self, task: BenchmarkTask, mode: RunMode, parallel: int) -> BenchRow:
        bus = new_event_bus(self._settings)

        def publish(kind: EventType, data: dict[str, Any]) -> None:
            if not bus.closed:
                bus.publish(kind, data)

        executor = self._services.executor(self._settings, publish)
        repo_source = self._services.repo_source(self._settings)
        search = self._services.web_search(self._settings)
        orchestrator = Orchestrator(
            settings=self._settings,
            model=self._services.model(self._settings),
            executor=executor,
            repo_source=repo_source,
            bus=bus,
            runs_dir=self._runs_dir,
            budget=self._budget,
            web_search=search,
        )
        request = RunRequest(
            repo_url=task.repo_url,
            task=task.task,
            ref=task.base_commit,
            origin="bench",
            base_image=_image(task),
            mode=mode,
            max_parallel=parallel,
            extra_packages=task.pip_packages,
        )
        try:
            run = await orchestrator.run(request)
        except GitHubError as exc:
            return self._failed_row(task, mode, bus.run_id, f"{exc.code}: {exc}")
        finally:
            await executor.close()
            await repo_source.aclose()
            if search is not None:
                await search.aclose()
        recheck, hidden, error = await self._check(task, run)
        report = run.report
        label = run.label or OutcomeLabel.NOT_VERIFIED
        return BenchRow(
            task_id=task.id,
            mode=mode,
            run_id=run.id,
            label=label,
            stop_reason=run.stop_reason or StopReason.INTERNAL_ERROR,
            duration_s=round(_duration(run), 1),
            cost_usd=round(report.cost_usd if report else 0.0, 6),
            max_seconds=self._budget.max_seconds,
            patch_lines=report.patch.changed_lines if report and report.patch else 0,
            recheck=recheck,
            hidden=hidden,
            agrees=None if hidden is None else hidden.passed == (label is OutcomeLabel.VERIFIED),
            check_error=error,
        )

    def _failed_row(self, task: BenchmarkTask, mode: RunMode, run_id: str, error: str) -> BenchRow:
        return BenchRow(
            task_id=task.id,
            mode=mode,
            run_id=run_id,
            label=OutcomeLabel.NOT_VERIFIED,
            stop_reason=StopReason.SETUP_FAILED,
            duration_s=0.0,
            cost_usd=0.0,
            max_seconds=self._budget.max_seconds,
            check_error=error,
        )

    # -- after-run checks ------------------------------------------------------------------

    async def _check(
        self, task: BenchmarkTask, run: Run
    ) -> tuple[RecheckResult | None, HiddenResult | None, str | None]:
        """Re-check a verified fix and run the hidden tests, in one fresh environment."""
        report = run.report
        if report is None or report.patch is None or report.patch.is_empty:
            return None, None, None
        redactor = Redactor(self._settings.secret_values())
        bus = EventBus(run.id, redact=redactor)
        writer = TraceWriter.for_run(self._checks_dir, run.id, redactor=redactor).attach(bus)

        def publish(kind: EventType, data: dict[str, Any]) -> None:
            if not bus.closed:
                bus.publish(kind, data)

        executor = self._services.executor(self._settings, publish)
        repo_source = self._services.repo_source(self._settings)
        tests = TestRunner(executor, timeout_s=self._budget.command_timeout_s, bus=bus)
        recheck: RecheckResult | None = None
        hidden: HiddenResult | None = None
        try:
            commands = install_commands(self._runs_dir / run.id / "trace.jsonl")
            installed = await self._fresh_environment(executor, repo_source, task, run, commands)
            if report.label is OutcomeLabel.VERIFIED:
                recheck = await self._recheck(executor, tests, installed, report, bus)
            test_patch = self._test_patch(task)
            if test_patch and task.hidden_fail_to_pass:
                hidden = await self._hidden_tests(
                    executor, tests, installed, task, report.patch.unified_diff, test_patch
                )
        except Exception as exc:  # a failed check is recorded; it never stops the benchmark
            return recheck, hidden, f"{type(exc).__name__}: {exc}"[:500]
        finally:
            writer.close()
            bus.close()
            await executor.close()
            await repo_source.aclose()
        return recheck, hidden, None

    async def _fresh_environment(
        self,
        executor: Executor,
        repo_source: RepoSource,
        task: BenchmarkTask,
        run: Run,
        commands: list[str],
    ) -> Snapshot:
        """Set up the run's commit again, with the install commands that worked in the run."""
        if not commands:
            raise CheckError("the run's trace has no successful install commands")
        location = parse_repo_url(task.repo_url)
        sha = run.repo.resolved_sha or task.base_commit
        with tempfile.TemporaryDirectory(prefix="fixproof-bench-") as tmp:
            tarball = await repo_source.download_tarball(
                location, sha, Path(tmp) / "repo.tgz", max_bytes=MAX_TARBALL_BYTES
            )
            snapshot = await executor.prepare_repo(tarball, _image(task))
        for command in commands:
            result, snapshot = await executor.run(
                snapshot, command, timeout_s=self._budget.install_timeout_s, mutate=True
            )
            if not result.ok:
                raise CheckError(f"install failed in the fresh environment: {command}")
        result, snapshot = await executor.run(
            snapshot, git_baseline_command(), timeout_s=GIT_TIMEOUT_S, mutate=True
        )
        if not result.ok:
            raise CheckError("could not record the git baseline in the fresh environment")
        return snapshot

    async def _recheck(
        self,
        executor: Executor,
        tests: TestRunner,
        installed: Snapshot,
        report: Report,
        bus: EventBus,
    ) -> RecheckResult:
        """Apply the patch to the fresh environment and run the verification rule again."""
        evidence, patch = report.evidence, report.patch
        if evidence is None or evidence.repro_test_id is None or patch is None:
            return RecheckResult(
                passed=False,
                label=OutcomeLabel.NOT_VERIFIED,
                detail="The report has no reproduction test to re-run.",
            )
        patched = await apply_patch(executor, installed, patch.unified_diff)
        fresh = Evidence(
            baseline=await tests.run(installed),
            repro_test_id=evidence.repro_test_id,
            repro_created=evidence.repro_created,
        )
        added_tests = [
            change.path
            for change in patch.files
            if change.status is FileStatus.ADDED and change.is_test_file
        ]
        repro_files = {path: await executor.read_file(patched, path) for path in added_tests}
        verification = await verify_fix(
            executor=executor,
            tests=tests,
            snapshot=patched,
            evidence=fresh,
            repro_files=repro_files,
            bus=bus,
        )
        passed = verification.label is OutcomeLabel.VERIFIED
        return RecheckResult(
            passed=passed,
            label=verification.label,
            detail="" if passed else verification.describe()[:2000],
        )

    async def _hidden_tests(
        self,
        executor: Executor,
        tests: TestRunner,
        installed: Snapshot,
        task: BenchmarkTask,
        agent_diff: str,
        test_patch: str,
    ) -> HiddenResult:
        """Run the hidden tests with the official test files, without and then with the fix.

        The agent's own changes to files that the official test patch also changes are left
        out, so the hidden tests always run as the official fix wrote them.
        """
        with_tests = await apply_patch(executor, installed, test_patch)
        rest = drop_files(agent_diff, set(changed_files(test_patch)))
        fixed = await apply_patch(executor, with_tests, rest) if rest.strip() else with_tests
        files = dict.fromkeys(
            test_id.split("::", 1)[0]
            for test_id in (*task.hidden_fail_to_pass, *task.hidden_pass_to_pass)
        )
        selector = " ".join(shlex.quote(path) for path in files)
        before = await tests.run(with_tests, selector)
        after = await tests.run(fixed, selector)
        fail_to_pass = {
            test_id: outcome_for(after, test_id) for test_id in task.hidden_fail_to_pass
        }
        expected = [t for t in task.hidden_pass_to_pass if outcome_for(before, t) == "passed"]
        broken = [t for t in expected if outcome_for(after, t) != "passed"]
        return HiddenResult(
            passed=all(value == "passed" for value in fail_to_pass.values()) and not broken,
            fail_to_pass=fail_to_pass,
            fails_before_fix=all(
                outcome_for(before, test_id) != "passed" for test_id in task.hidden_fail_to_pass
            ),
            pass_to_pass_checked=len(expected),
            pass_to_pass_broken=broken,
        )

    def _test_patch(self, task: BenchmarkTask) -> str | None:
        if not task.hidden_test_patch:
            return None
        # Bytes, not text mode: a patch may change files with CRLF line endings.
        return (self._tasks_file.parent / task.hidden_test_patch).read_bytes().decode("utf-8")


# -- helpers -------------------------------------------------------------------------------


async def apply_patch(executor: Executor, snapshot: Snapshot, diff: str) -> Snapshot:
    """Apply a git diff inside the environment with ``git apply``; return the new snapshot.

    Raises:
        CheckError: If the diff does not apply.
    """
    text = diff if diff.endswith("\n") else diff + "\n"
    written = await executor.write_files(snapshot, {PATCH_FILE: text.encode()})
    result, applied = await executor.run(
        written,
        f"git apply --whitespace=nowarn {PATCH_FILE} && rm -f {PATCH_FILE}",
        timeout_s=GIT_TIMEOUT_S,
        mutate=True,
    )
    if not result.ok:
        message = (result.stderr or result.stdout).strip()[:300]
        raise CheckError(f"the patch does not apply: {message}")
    return applied


def install_commands(trace_file: Path) -> list[str]:
    """Return a run's install commands that succeeded, in order, from its trace."""
    return [
        str(event.data["command"])
        for event in read_trace(trace_file)
        if event.type is EventType.INSTALL_RESULT
        and event.data.get("exit_code") == 0
        and not event.data.get("timed_out")
    ]


def outcome_for(run: TestRun, test_id: str) -> str:
    """Return a hidden test's outcome in ``run`` (an outcome value, or ``missing``).

    SWE-bench cuts some parametrized IDs at their first space; such an ID matches every test
    that starts with it, and passes only if all of them passed.
    """
    found = run.outcome_of(test_id)
    if found is not None:
        return found.value
    if "[" in test_id:
        matches = [r.outcome for r in run.results if r.node_id.startswith(test_id)]
        if matches:
            worst = next((o for o in matches if o is not TestOutcome.PASSED), TestOutcome.PASSED)
            return worst.value
    return "missing"


def percentile(values: Iterable[float], q: float) -> float:
    """Return the ``q``-th percentile by the nearest-rank method (0.0 when there are none)."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(1, math.ceil(q / 100 * len(ordered))) - 1]


def summarize(rows: Sequence[BenchRow], mode: RunMode) -> BenchSummary:
    """Compute the numbers of ``mode``'s rows."""
    chosen = [row for row in rows if row.mode is mode]
    count = len(chosen)
    verified = sum(1 for row in chosen if row.label is OutcomeLabel.VERIFIED)
    rechecked = [row for row in chosen if row.recheck is not None]
    checked = [row for row in chosen if row.agrees is not None]
    durations = [row.duration_s for row in chosen]
    return BenchSummary(
        mode=mode,
        tasks=count,
        verified=verified,
        needs_review=sum(1 for row in chosen if row.label is OutcomeLabel.NEEDS_REVIEW),
        not_verified=sum(1 for row in chosen if row.label is OutcomeLabel.NOT_VERIFIED),
        verified_rate=verified / count if count else 0.0,
        rechecked=len(rechecked),
        recheck_failures=sum(
            1 for row in rechecked if row.recheck is not None and not row.recheck.passed
        ),
        hidden_checked=len(checked),
        hidden_agree=sum(1 for row in checked if row.agrees),
        p50_s=percentile(durations, 50),
        p90_s=percentile(durations, 90),
        within_15_min=_share(sum(1 for d in durations if d <= TIME_TARGET_S), count),
        within_max=_share(
            sum(1 for row in chosen if row.duration_s <= row.max_seconds + REPORT_GRACE_S), count
        ),
        cost_usd=round(sum(row.cost_usd for row in chosen), 6),
    )


def summaries(results: BenchResults) -> list[BenchSummary]:
    """Return one summary per mode present, single path first."""
    present = {row.mode for row in results.rows}
    return [summarize(results.rows, mode) for mode in _MODE_ORDER if mode in present]


def paired_rows(rows: Sequence[BenchRow]) -> list[PairedRow]:
    """Pair each task's single-path and parallel labels, in task order."""
    labels: dict[str, dict[RunMode, OutcomeLabel]] = {}
    for row in rows:
        labels.setdefault(row.task_id, {})[row.mode] = row.label
    return [
        PairedRow(
            task_id=task_id, single=by_mode[RunMode.SINGLE], parallel=by_mode[RunMode.PARALLEL]
        )
        for task_id, by_mode in labels.items()
        if RunMode.SINGLE in by_mode and RunMode.PARALLEL in by_mode
    ]


def describe_row(row: BenchRow) -> str:
    """Return one progress line for a finished run."""
    parts = [
        f"{row.task_id} ({row.mode.value}): {row.label.value} ({row.stop_reason.value}) "
        f"in {_minutes(row.duration_s)}, ${row.cost_usd:.4f}"
    ]
    if row.recheck is not None:
        parts.append("re-check " + ("passed" if row.recheck.passed else "FAILED"))
    if row.hidden is not None:
        parts.append("hidden tests " + ("pass" if row.hidden.passed else "fail"))
    if row.check_error:
        parts.append(f"check error: {row.check_error}")
    return "; ".join(parts)


def render_summary(results: BenchResults) -> str:
    """Render the results as Markdown (``summary.md``, and the README's benchmark table)."""
    budget = results.budget
    lines = ["# FixProof benchmark results", ""]
    if results.dev_only:
        note = results.platform_note or "Not the hackathon platform."
        lines += [
            f"> **{note}** These results did not come from Nebius Token Factory with Token "
            "Factory Sandboxes; do not present them as hackathon results.",
            "",
        ]
    lines += [
        f"- Date: {results.created_at:%Y-%m-%d %H:%M} UTC",
        f"- Tasks: {len({row.task_id for row in results.rows})} from `{results.tasks_file}`",
        f"- Executor: {results.executor}",
        "- Models: " + ", ".join(f"{role} `{model}`" for role, model in results.models.items()),
        f"- Budget per run: {budget.max_steps} steps, {budget.max_seconds / 60:g} min, "
        f"${budget.max_cost_usd:.2f}",
        "",
        "| Mode | Tasks | Verified | Needs review | Re-check failures | Hidden-test agreement "
        "| p50 time | p90 time | Within 15 min | Within max time | Cost |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {s.mode.value} | {s.tasks} | {s.verified} ({s.verified_rate:.0%}) | {s.needs_review} "
        f"| {s.recheck_failures} of {s.rechecked} | {s.hidden_agree} of {s.hidden_checked} "
        f"| {_minutes(s.p50_s)} | {_minutes(s.p90_s)} | {s.within_15_min:.0%} "
        f"| {s.within_max:.0%} | ${s.cost_usd:.2f} |"
        for s in summaries(results)
    ]
    lines += [
        "",
        "- **Verified**: the harness proved the fix (the reproduction test passed 3 times in a "
        "row and no test that passed before fails now).",
        "- **Re-check failures**: verified fixes whose evidence failed when it was re-run in a "
        "fresh environment (the target is 0).",
        "- **Hidden-test agreement**: runs where the task's hidden reference tests (from the "
        "official fix, never shown to the agent) pass exactly when the label is Verified.",
        f"- **Within max time**: runs that ended within their time budget plus {REPORT_GRACE_S} s "
        "for the final report.",
        "",
        "## Per task",
        "",
        "| Task | Mode | Label | Stop reason | Time | Cost | Changed lines | Re-check "
        "| Hidden tests |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {row.task_id} | {row.mode.value} | {row.label.value} | {row.stop_reason.value} "
        f"| {_minutes(row.duration_s)} | ${row.cost_usd:.4f} | {row.patch_lines} "
        f"| {_recheck_cell(row)} | {_hidden_cell(row)} |"
        for row in results.rows
    ]
    pairs = paired_rows(results.rows)
    if pairs:
        only_parallel = [
            p.task_id
            for p in pairs
            if p.parallel is OutcomeLabel.VERIFIED and p.single is not OutcomeLabel.VERIFIED
        ]
        lines += [
            "",
            "## Single path versus parallel hypotheses",
            "",
            "Both modes ran with the same budget per run.",
            "",
            "| Task | Single path | Parallel |",
            "|---|---|---|",
            *(f"| {p.task_id} | {p.single.value} | {p.parallel.value} |" for p in pairs),
            "",
            f"Parallel mode verified {len(only_parallel)} task(s) that single-path mode did not"
            + (f": {', '.join(only_parallel)}." if only_parallel else "."),
        ]
    errors = [row for row in results.rows if row.check_error]
    if errors:
        lines += ["", "## Check errors", ""]
        lines += [f"- {row.task_id} ({row.mode.value}): {row.check_error}" for row in errors]
    return "\n".join(lines) + "\n"


def write_results(out_dir: Path, results: BenchResults) -> None:
    """Write ``results.json`` and ``summary.md`` to ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        results.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "summary.md").write_text(render_summary(results), encoding="utf-8")


def load_results(results_dir: Path) -> BenchResults:
    """Read ``results.json`` from a results folder.

    Raises:
        ValueError: If the file is missing or is not a valid results file.
    """
    path = results_dir / "results.json"
    try:
        return BenchResults.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except ValidationError as exc:
        raise ValueError(f"{path} is not a valid results file: {exc.errors()[0]['msg']}") from exc


def default_results_dir(root: Path = Path("bench/results"), today: date | None = None) -> Path:
    """Return ``<root>/<date>``, or ``<root>/<date>-N`` if that already holds results."""
    day = (today or utc_now().date()).isoformat()
    candidate, number = root / day, 1
    while (candidate / "results.json").exists():
        number += 1
        candidate = root / f"{day}-{number}"
    return candidate


def _image(task: BenchmarkTask) -> str:
    return task.image_tag or f"python:{task.python}"


def _duration(run: Run) -> float:
    if run.report is not None and run.report.duration_s:
        return run.report.duration_s
    if run.started_at is not None and run.ended_at is not None:
        return (run.ended_at - run.started_at).total_seconds()
    return 0.0


def _share(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


def _minutes(seconds: float) -> str:
    return f"{seconds / 60:.1f} min"


def _recheck_cell(row: BenchRow) -> str:
    if row.recheck is None:
        return "-"
    return "passed" if row.recheck.passed else f"FAILED ({row.recheck.label.value})"


def _hidden_cell(row: BenchRow) -> str:
    if row.hidden is None:
        return "check error" if row.check_error else "-"
    result = "pass" if row.hidden.passed else "fail"
    return f"{result} ({'agrees' if row.agrees else 'disagrees'})"
