"""The orchestrator: one task through the state machine in data-model.md.

``queued → setting_up → baseline → planning → reproducing → fixing ⇄ verifying → reporting → done``

- The initial plan is requested right after intake, from the task and the GitHub file tree, while
  setup continues; the refined plan follows the baseline test run (SC-006).
- The harness, not the model, verifies every fix and computes the label (research R8).
- Reporting always runs, also after a stop, a budget limit, or a failure, so partial results are
  returned (FR-012); ``run_finished`` is always the last event.
- ``stop()`` cancels in-flight model and sandbox work; reporting then has 10 seconds.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import shlex
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, TypeVar

from fixproof.agent import prompts
from fixproof.agent.hypotheses import BranchSetup, HypothesisRunner
from fixproof.agent.prompts import Plan
from fixproof.agent.report import (
    build_report,
    render_markdown,
    report_event,
    validate_citations,
    write_report_files,
)
from fixproof.agent.verify import Verification, label_rank, verify_fix
from fixproof.agent.worker import ModelGateway, Worker, WorkerStatus
from fixproof.budget import BudgetExceeded, BudgetTracker
from fixproof.config import Settings
from fixproof.events import EventBus, EventType
from fixproof.llm.client import ModelClient, ModelUnavailableError
from fixproof.models import (
    Attempt,
    AttemptStatus,
    Budget,
    Citation,
    Evidence,
    Hypothesis,
    HypothesisRow,
    ModelRole,
    OutcomeLabel,
    Patch,
    RepoRef,
    Report,
    Run,
    RunMode,
    RunStatus,
    Snapshot,
    StopReason,
    Task,
    TaskKind,
    TestOutcome,
    new_run_id,
    utc_now,
)
from fixproof.repo.github import (
    GitHubError,
    RepoLocation,
    RepoSource,
    parse_issue_url,
    parse_repo_url,
    read_tarball_text,
    tarball_paths,
)
from fixproof.sandbox.executor import (
    CommandResult,
    Executor,
    ExecutorError,
    compute_patch,
    git_baseline_command,
)
from fixproof.sandbox.pytest_results import TestRunner
from fixproof.sandbox.recipes import detect_install_commands, pin_command
from fixproof.tools.handlers import ToolContext, ToolPhase, WebSearch, forbidden_reason
from fixproof.tools.registry import build_registry
from fixproof.tools.schemas import FinishArgs
from fixproof.tools.toolbox import ToolBox
from fixproof.trace import Redactor, TraceWriter

MAX_TARBALL_BYTES = 300 * 1024 * 1024
FLAKY_RERUN_LIMIT = 50
GIT_TIMEOUT_S = 120
_INSTALL_PREFIXES = (
    "python -m pip install ",
    "python3 -m pip install ",
    "pip install ",
    "pip3 install ",
)
_UNSAFE_SHELL = re.compile(r"[;|`<>\n]|\$\(")
_T = TypeVar("_T")


def new_event_bus(settings: Settings, run_id: str | None = None) -> EventBus:
    """Create a run's event bus that redacts every configured secret (FR-020)."""
    return EventBus(run_id or new_run_id(), redact=Redactor(settings.secret_values()))


def safe_install_command(command: str) -> bool:
    """Return whether a model-suggested install command may run.

    Only ``pip install`` commands are accepted, optionally joined with ``&&``; pipes, command
    substitution, redirection, and anything ``run_command`` forbids (except ``pip install``)
    are rejected.
    """
    text = command.strip()
    if not text or len(text) > 500 or _UNSAFE_SHELL.search(text):
        return False
    for part in (p.strip() for p in text.split("&&")):
        if not part.startswith(_INSTALL_PREFIXES):
            return False
        reason = forbidden_reason(part)
        if reason is not None and reason != "pip install":
            return False
    return True


@dataclass(frozen=True)
class RunRequest:
    """What to run: a public repository, an optional revision, and exactly one task."""

    repo_url: str
    task: Task
    ref: str | None = None
    origin: Literal["cli", "web", "bench"] = "cli"
    base_image: str | None = None  # overrides FIXPROOF_BASE_IMAGE (e.g. a task's Python version)
    mode: RunMode = RunMode.SINGLE
    max_parallel: int = 3  # parallel mode: branches at once (1-3)
    exhaustive: bool = False  # parallel mode: keep running branches after the first verified one
    extra_packages: tuple[str, ...] = ()  # pins installed after the recipe (benchmark tasks)


@dataclass(frozen=True)
class _ReproductionCheck:
    test_id: str | None
    reason: str


class Orchestrator:
    """Runs one task end to end and always produces a report.

    Args:
        settings: Configuration (models, sampling, base image, secrets to redact).
        model: Model client (Token Factory, or a fake in tests).
        executor: Isolated environment (Token Factory Sandboxes, or a dev/test executor).
        repo_source: GitHub intake.
        bus: The run's event bus (see ``new_event_bus``); the run ID comes from it.
        runs_dir: Directory receiving ``<run_id>/`` with the trace and report files.
        budget: Limits for this run.
        clock: Monotonic clock, injectable for tests.
        max_repo_kb: Largest accepted repository (the web demo sets this).
        max_tarball_bytes: Largest accepted source archive.
        initial_plan_timeout_s: Time the initial plan may take before a default plan is shown.
        stop_deadline_s: Time reporting may take after a stop.
        max_repro_turns: Model calls per reproduction attempt.
        max_repro_checks: Reproductions the harness checks before giving up.
        max_fix_rounds: Fix and verify rounds (with planner re-diagnosis between them).
        web_search: Optional search backend; ``web_search`` is offered only when set.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        model: ModelClient,
        executor: Executor,
        repo_source: RepoSource,
        bus: EventBus,
        runs_dir: Path,
        budget: Budget,
        clock: Callable[[], float] = time.monotonic,
        max_repo_kb: int | None = None,
        max_tarball_bytes: int = MAX_TARBALL_BYTES,
        initial_plan_timeout_s: float = 25.0,
        stop_deadline_s: float = 10.0,
        max_repro_turns: int = 15,
        max_repro_checks: int = 3,
        max_fix_rounds: int = 3,
        web_search: WebSearch | None = None,
    ) -> None:
        self.bus = bus
        self._settings = settings
        self._executor = executor
        self._repo_source = repo_source
        self._runs_dir = runs_dir
        self._limits = budget
        self._budget = BudgetTracker(budget, clock=clock)
        self._model = model
        self._gateway = ModelGateway(model, self._budget, bus, settings.sampling())
        self._tests = TestRunner(executor, timeout_s=budget.command_timeout_s, bus=bus)
        self._registry = build_registry(web_search=web_search is not None)
        self._web_search = web_search
        self._max_repo_kb = max_repo_kb
        self._max_tarball_bytes = max_tarball_bytes
        self._initial_plan_timeout_s = initial_plan_timeout_s
        self._stop_deadline_s = stop_deadline_s
        self._max_repro_turns = max_repro_turns
        self._max_repro_checks = max_repro_checks
        self._max_fix_rounds = max_fix_rounds

        self._run: Run | None = None
        self._main: asyncio.Task[None] | None = None
        self._stop_requested = False
        self._stop_reason: StopReason | None = None
        self._initial_plan: asyncio.Task[Plan] | None = None
        self._base_image = settings.base_image
        self._plan: Plan = prompts.DEFAULT_PLAN
        self._paths: list[str] = []
        self._installed: Snapshot | None = None
        self._repro: Snapshot | None = None
        self._evidence: Evidence | None = None
        self._repro_files: dict[str, bytes] = {}
        self._worker: Worker | None = None
        self._best: Verification | None = None
        self._best_finish: FinishArgs | None = None
        self._last_finish: FinishArgs | None = None
        self._report_published = False
        self._mode = RunMode.SINGLE
        self._max_parallel = 3
        self._exhaustive = False
        self._extra_packages: tuple[str, ...] = ()
        self._hypotheses: list[Hypothesis] | None = None
        self._hypothesis_rows: list[HypothesisRow] = []

    # -- public API ----------------------------------------------------------------------

    @property
    def run_id(self) -> str:
        """The run ID (from the event bus)."""
        return self.bus.run_id

    @property
    def run_dir(self) -> Path:
        """Directory holding this run's trace and report files."""
        return self._runs_dir / self.run_id

    def stop(self) -> None:
        """Stop the run: cancel in-flight model and sandbox work, then report partial results."""
        self._stop_requested = True
        if self._main is not None and not self._main.done():
            self._main.cancel()

    async def run(self, request: RunRequest) -> Run:
        """Run ``request`` to completion (or until stopped) and return the finished run.

        Raises:
            GitHubError: ``invalid_repo`` if the repository URL is malformed (nothing ran).
        """
        location = parse_repo_url(request.repo_url)
        run = Run(
            id=self.run_id,
            repo=RepoRef(
                url=location.url,
                owner=location.owner,
                name=location.name,
                ref=request.ref or location.ref,
            ),
            task=request.task,
            mode=request.mode,
            budget=self._limits,
            origin=request.origin,
            started_at=utc_now(),
        )
        self._run = run
        self._budget.restart_clock()  # time spent waiting in a demo queue does not count
        self._base_image = request.base_image or self._settings.base_image
        self._mode = request.mode
        self._max_parallel = max(1, min(request.max_parallel, self._limits.max_parallel))
        self._exhaustive = request.exhaustive
        self._extra_packages = request.extra_packages
        redactor = Redactor(self._settings.secret_values())
        writer = TraceWriter.for_run(self._runs_dir, self.run_id, redactor=redactor).attach(
            self.bus
        )
        self._publish_run_started(request)  # always first, even for a run stopped before it began
        main = asyncio.create_task(self._pipeline(location))
        self._main = main
        if self._stop_requested:
            main.cancel()
        cancelled_from_outside = False
        try:
            try:
                await asyncio.wait({main})
            except asyncio.CancelledError:
                cancelled_from_outside = True
                self.stop()
                await asyncio.wait({main})
            if main.cancelled() and self._stop_reason is None:
                self._stop_reason = StopReason.USER_STOP
            await self._report_with_deadline()
        finally:
            self._finish_run(run)
            writer.close()
            self.bus.close()
        if cancelled_from_outside:
            raise asyncio.CancelledError
        return run

    # -- pipeline ------------------------------------------------------------------------

    async def _pipeline(self, location: RepoLocation) -> None:
        try:
            await self._setting_up(location)
            for phase in (
                self._baseline_phase,
                self._planning_phase,
                self._reproducing_phase,
                self._fixing_phase,
            ):
                if self._stop_reason is not None:
                    return
                await phase()
            if self._stop_reason is None:
                self._stop_reason = StopReason.COMPLETED
        except BudgetExceeded as exc:
            self._stop_reason = self._stop_reason or exc.reason
            self.bus.publish(
                EventType.BUDGET, {**self._budget.snapshot(), "limit_hit": exc.reason.value}
            )
        except ModelUnavailableError as exc:
            self._fail(StopReason.SERVICE_UNAVAILABLE, "model", str(exc))
        except ExecutorError as exc:
            self._fail(StopReason.SERVICE_UNAVAILABLE, "sandbox", str(exc))
        except GitHubError as exc:
            self._fail(StopReason.SETUP_FAILED, "intake", str(exc))
        except Exception as exc:
            self._fail(StopReason.INTERNAL_ERROR, "orchestrator", f"{type(exc).__name__}: {exc}")
        finally:
            if self._initial_plan is not None and not self._initial_plan.done():
                self._initial_plan.cancel()

    def _publish_run_started(self, request: RunRequest) -> None:
        task = self._require(self._run).task
        self.bus.publish(
            EventType.RUN_STARTED,
            {
                "repo_url": request.repo_url,
                "ref": request.ref,
                "task": {"kind": task.kind.value, "value": task.value},
                "mode": request.mode.value,
                "budget": self._limits.model_dump(),
                "models": self._settings.models_by_role(),
                "sampling": self._settings.sampling(),
                "executor": self._executor.name,
            },
        )

    async def _setting_up(self, location: RepoLocation) -> None:
        run = self._require(self._run)
        self._transition(RunStatus.SETTING_UP)
        repo = await self._repo_source.get_repo(location, max_kb=self._max_repo_kb)
        ref = run.repo.ref or repo.default_branch or repo.ref
        if not ref:
            raise GitHubError("invalid_repo", "Could not determine which revision to use.")
        sha = await self._repo_source.resolve_ref(location, ref)
        run.repo = repo.model_copy(update={"ref": ref, "resolved_sha": sha})
        run.task = await self._load_task(location, run.task)
        tree = await self._repo_source.get_tree(location, sha)
        self._initial_plan = asyncio.create_task(self._make_initial_plan(run.task, tree))
        await asyncio.sleep(0)  # let the planner request start before the slower setup steps

        with tempfile.TemporaryDirectory(prefix="fixproof-") as tmp:
            tarball = await self._repo_source.download_tarball(
                location, sha, Path(tmp) / "repo.tgz", max_bytes=self._max_tarball_bytes
            )
            self.bus.publish(
                EventType.REPO_FETCHED,
                {"resolved_sha": sha, "size_kb": max(1, tarball.stat().st_size // 1024)},
            )
            self._paths = tarball_paths(tarball)
            commands = detect_install_commands(
                self._paths, lambda path: read_tarball_text(tarball, path)
            )
            if self._extra_packages:
                commands.append(pin_command(self._extra_packages))
            self._budget.check(steps=False)
            source = await self._executor.prepare_repo(tarball, self._base_image)
        source = await self._key_snapshot(source, "source")

        installed = await self._install(source, commands)
        if installed is None:
            return
        self._budget.check(steps=False)
        result, committed = await self._executor.run(
            installed, git_baseline_command(), timeout_s=GIT_TIMEOUT_S, mutate=True
        )
        if not result.ok:
            self._fail(
                StopReason.SETUP_FAILED,
                "setup",
                f"Could not record the git baseline: {_tail(result, 500)}",
            )
            return
        self._installed = await self._key_snapshot(committed, "installed")

    async def _load_task(self, location: RepoLocation, task: Task) -> Task:
        if task.kind is not TaskKind.ISSUE:
            return task
        number = parse_issue_url(task.value, location)
        title, body = await self._repo_source.get_issue(location, number)
        return Task(kind=task.kind, value=task.value, issue_title=title, issue_body=body[:8000])

    async def _make_initial_plan(self, task: Task, tree: list[str]) -> Plan:
        """Ask the planner for the initial plan; fall back to a default plan if it is slow."""
        plan: Plan | None = None
        problem: str | None = None
        try:
            reply = await asyncio.wait_for(
                self._gateway.complete(
                    ModelRole.PLANNER, prompts.initial_plan_messages(task, tree)
                ),
                self._initial_plan_timeout_s,
            )
            plan = prompts.parse_plan(reply.content)
            if plan is None:
                problem = "the planner's answer contained no usable plan"
        except TimeoutError:
            problem = f"the planner did not answer within {self._initial_plan_timeout_s:.0f} s"
        except (BudgetExceeded, ModelUnavailableError) as exc:
            problem = str(exc)
        if problem is not None:
            self._error("plan", f"Showing a default initial plan: {problem}.")
        plan = plan or prompts.DEFAULT_PLAN
        self._publish_plan(plan, "initial")
        return plan

    async def _install(self, snapshot: Snapshot, commands: list[str]) -> Snapshot | None:
        """Run the install recipe, with one model-suggested retry; ``None`` if setup failed."""
        pending = list(commands)
        index = 0
        retried = False
        while index < len(pending):
            command = pending[index]
            self._budget.check(steps=False)
            result, after = await self._executor.run(
                snapshot, command, timeout_s=self._limits.install_timeout_s, mutate=True
            )
            self.bus.publish(
                EventType.INSTALL_RESULT,
                {
                    "command": command,
                    "exit_code": result.exit_code,
                    "elapsed_s": round(result.elapsed_s, 3),
                    "timed_out": result.timed_out,
                    "output_tail": _tail(result, 2000),
                },
            )
            if result.ok:
                snapshot, index = after, index + 1
                continue
            if retried:
                self._fail(
                    StopReason.SETUP_FAILED,
                    "setup",
                    f"Installing the project failed twice (last command: {command}).",
                )
                return None
            retried = True
            suggestion = await self._suggest_install(command, result)
            if suggestion is None:
                self._fail(
                    StopReason.SETUP_FAILED,
                    "setup",
                    f"Installing the project failed ({command}) and no safe alternative "
                    "command was suggested.",
                )
                return None
            pending[index] = suggestion
        return snapshot

    async def _suggest_install(self, command: str, result: CommandResult) -> str | None:
        messages = prompts.install_retry_messages(command, _tail(result, 3000), self._paths)
        reply = await self._gateway.complete(ModelRole.WORKER, messages)
        suggestion = prompts.parse_install_command(reply.content)
        if suggestion is None or not safe_install_command(suggestion):
            self._error("setup", f"Rejected the suggested install command: {suggestion!r}.")
            return None
        return suggestion

    async def _baseline_phase(self) -> None:
        installed = self._require(self._installed)
        self._transition(RunStatus.BASELINE)
        self._budget.check(steps=False)
        baseline = await self._tests.run(installed)
        if baseline.timed_out:
            self._error("baseline", "The baseline test run timed out; results may be incomplete.")
        failing = sorted(baseline.failed_ids)
        flaky: list[str] = []
        if failing and len(failing) <= FLAKY_RERUN_LIMIT:
            self._budget.check(steps=False)
            rerun = await self._tests.run(installed, " ".join(shlex.quote(n) for n in failing))
            flaky = [n for n in failing if rerun.outcome_of(n) is TestOutcome.PASSED]
        self._evidence = Evidence(baseline=baseline, baseline_flaky=flaky)
        self._require(self._run).evidence = self._evidence

    async def _planning_phase(self) -> None:
        run = self._require(self._run)
        self._transition(RunStatus.PLANNING)
        initial = await self._initial_plan if self._initial_plan else prompts.DEFAULT_PLAN
        reply = await self._gateway.complete(
            ModelRole.PLANNER,
            prompts.refined_plan_messages(run.task, self._paths, self._evidence, initial),
        )
        plan = prompts.parse_plan(reply.content)
        if plan is None:
            self._error("plan", "The refined plan was not usable; keeping the initial plan.")
        self._plan = plan or initial
        self._publish_plan(self._plan, "refined")
        if self._mode is RunMode.PARALLEL:
            self._hypotheses = await self._make_hypotheses()

    async def _reproducing_phase(self) -> None:
        run = self._require(self._run)
        self._transition(RunStatus.REPRODUCING)
        if run.task.kind is TaskKind.FAILING_TEST:
            await self._reproduce_given_test(run.task.value)
        else:
            await self._reproduce_with_worker(run.task)

    async def _reproduce_given_test(self, test_id: str) -> None:
        installed = self._require(self._installed)
        evidence = self._require(self._evidence)
        self._budget.check(steps=False)
        result = await self._tests.run(installed, shlex.quote(test_id))
        outcome = result.outcome_of(test_id)
        fails = outcome in (TestOutcome.FAILED, TestOutcome.ERROR)
        self.bus.publish(
            EventType.REPRO_STATUS,
            {"repro_test_id": test_id, "created": False, "fails_before": fails},
        )
        if not fails:
            state = "passes" if outcome is TestOutcome.PASSED else "was not found or did not run"
            self._fail(
                StopReason.NOT_REPRODUCIBLE,
                "reproduce",
                f"The test {test_id} {state} before any change, so there is no failure to fix.",
            )
            return
        evidence.repro_test_id = test_id
        evidence.repro_created = False
        evidence.repro_before = result
        self._repro = await self._key_snapshot(installed, "repro")

    async def _reproduce_with_worker(self, task: Task) -> None:
        installed = self._require(self._installed)
        evidence = self._require(self._evidence)
        worker = self._new_worker(installed, ToolPhase.REPRODUCE)
        context = worker.toolbox.context
        message = prompts.reproduce_message(task, self._plan, self._paths, evidence)
        for _ in range(self._max_repro_checks):
            result = await worker.run(message, max_turns=self._max_repro_turns)
            if result.status is WorkerStatus.INVALID_TOOL_CALLS:
                self._fail(
                    StopReason.INVALID_TOOL_CALLS,
                    "worker",
                    "The model made 3 invalid tool calls in a row.",
                )
                return
            if result.status is WorkerStatus.MAX_TURNS:
                break
            self._last_finish = result.finish
            check = await self._check_reproduction(context)
            if check.test_id is not None:
                created = sorted(p for p in context.created_files if _is_test_module(p))
                self._repro_files = {
                    p: await self._executor.read_file(context.snapshot, p) for p in created
                }
                self._repro = await self._key_snapshot(context.snapshot, "repro")
                context.snapshot = self._repro
                return
            message = prompts.reproduction_feedback(check.reason)
        self.bus.publish(
            EventType.REPRO_STATUS,
            {"repro_test_id": None, "created": True, "fails_before": False},
        )
        self._fail(
            StopReason.NOT_REPRODUCIBLE,
            "reproduce",
            "The agent could not write a test that fails before the fix.",
        )

    async def _check_reproduction(self, context: ToolContext) -> _ReproductionCheck:
        """Run the worker's new test files; the first failing test becomes the reproduction."""
        evidence = self._require(self._evidence)
        created = sorted(p for p in context.created_files if _is_test_module(p))
        if not created:
            return _ReproductionCheck(
                None,
                "you did not create a new test file (for example tests/test_fixproof_repro.py).",
            )
        self._budget.check(steps=False)
        run = await self._tests.run(context.snapshot, " ".join(shlex.quote(p) for p in created))
        mine = [r for r in run.results if r.node_id.split("::", 1)[0] in created]
        failing = sorted(r.node_id for r in mine if r.outcome is TestOutcome.FAILED)
        errors = [r for r in mine if r.outcome is TestOutcome.ERROR]
        if failing:
            evidence.repro_test_id = failing[0]
            evidence.repro_created = True
            evidence.repro_before = run
            self.bus.publish(
                EventType.REPRO_STATUS,
                {"repro_test_id": failing[0], "created": True, "fails_before": True},
            )
            return _ReproductionCheck(failing[0], "")
        files = ", ".join(created)
        if errors:
            detail = (errors[0].message or "error").splitlines()[0][:300]
            reason = (
                f"{errors[0].node_id} errored instead of failing ({detail}). Make it fail on an "
                "assertion about the bug."
            )
        elif not mine:
            reason = f"pytest collected no tests from {files}: {run.output_tail[-500:]}"
        else:
            reason = f"every test in {files} passed, so it does not reproduce the bug."
        return _ReproductionCheck(None, reason)

    async def _make_hypotheses(self) -> list[Hypothesis] | None:
        """Ask the planner for competing hypotheses, repairing one unusable answer."""
        run = self._require(self._run)
        limit = self._max_parallel
        messages = prompts.hypotheses_messages(
            run.task, self._paths, self._evidence, self._plan, limit
        )
        reply = await self._gateway.complete(ModelRole.PLANNER, messages)
        hypotheses = prompts.parse_hypotheses(reply.content, limit)
        if hypotheses is None:
            repair = [
                *messages,
                {"role": "assistant", "content": reply.content or ""},
                {"role": "user", "content": prompts.hypotheses_repair_message(limit)},
            ]
            reply = await self._gateway.complete(ModelRole.PLANNER, repair)
            hypotheses = prompts.parse_hypotheses(reply.content, limit)
        if hypotheses is None:
            self._error(
                "plan", "The planner gave no usable hypotheses; continuing with a single attempt."
            )
            return None
        self.bus.publish(
            EventType.HYPOTHESES,
            {
                "items": [
                    {
                        "id": h.id,
                        "statement": h.statement,
                        "suspected_files": list(h.suspected_files),
                    }
                    for h in hypotheses
                ]
            },
        )
        return hypotheses

    async def _parallel_fixing_phase(self, hypotheses: list[Hypothesis]) -> None:
        """Test every hypothesis in its own sandbox branch and keep the smallest verified fix."""
        run = self._require(self._run)
        self._transition(RunStatus.FIXING)
        setup = BranchSetup(
            model=self._model,
            sampling=self._settings.sampling(),
            registry=self._registry,
            executor=self._executor,
            tests=self._tests,
            bus=self.bus,
            limits=self._limits,
            task=run.task,
            plan=self._plan,
            paths=self._paths,
            repro=self._require(self._repro),
            evidence=self._require(self._evidence),
            repro_files=self._repro_files,
            web_search=self._web_search,
        )
        runner = HypothesisRunner(
            setup, budget=self._budget, max_parallel=self._max_parallel, exhaustive=self._exhaustive
        )
        outcome = await runner.run(hypotheses)
        run.attempts.extend(branch.attempt for branch in outcome.branches)
        self._hypothesis_rows = outcome.rows
        for branch in outcome.branches:
            self._gateway.models_used.update(branch.models_used)
        winner = outcome.winner
        if winner is not None and winner.verification is not None:
            self._best, self._best_finish = winner.verification, winner.finish
            self._last_finish = winner.finish
        if outcome.service_error is not None:
            raise outcome.service_error
        if all(b.attempt.status is AttemptStatus.BUDGET_EXHAUSTED for b in outcome.branches):
            self._budget.check()  # report the run-level limit that stopped every branch

    async def _fixing_phase(self) -> None:
        if self._hypotheses:
            await self._parallel_fixing_phase(self._hypotheses)
            return
        run = self._require(self._run)
        repro = self._require(self._repro)
        evidence = self._require(self._evidence)
        attempt = Attempt(id="a1", start_snapshot=repro, current_snapshot=repro)
        run.attempts.append(attempt)
        include_context = self._worker is None
        worker = self._worker or self._new_worker(repro, ToolPhase.FIX)
        context = worker.toolbox.context
        context.snapshot = repro
        context.enter_phase(ToolPhase.FIX)
        context.frozen_files = set(self._repro_files)  # the evidence must not change now
        worker.attempt_id = attempt.id
        message = prompts.fix_message(
            run.task, self._plan, evidence, paths=self._paths, include_context=include_context
        )
        try:
            for round_number in range(1, self._max_fix_rounds + 1):
                self._transition(RunStatus.FIXING)
                result = await worker.run(message)
                attempt.current_snapshot = context.snapshot
                attempt.steps = worker.steps
                if result.status is WorkerStatus.INVALID_TOOL_CALLS:
                    self._fail(
                        StopReason.INVALID_TOOL_CALLS,
                        "worker",
                        "The model made 3 invalid tool calls in a row.",
                    )
                    return
                self._last_finish = result.finish
                self._transition(RunStatus.VERIFYING)
                verification = await verify_fix(
                    executor=self._executor,
                    tests=self._tests,
                    snapshot=context.snapshot,
                    evidence=evidence,
                    repro_files=self._repro_files,
                    bus=self.bus,
                    attempt_id=attempt.id,
                    budget=self._budget,
                )
                attempt.patch = verification.patch
                attempt.evidence = verification.evidence
                attempt.label = verification.label
                if self._is_better(verification):
                    self._best, self._best_finish = verification, result.finish
                if (
                    verification.label is OutcomeLabel.VERIFIED
                    or round_number == self._max_fix_rounds
                ):
                    return
                message = await self._rediagnose(verification, attempt.id)
        except BudgetExceeded:
            attempt.status = AttemptStatus.BUDGET_EXHAUSTED
            raise
        except asyncio.CancelledError:
            attempt.status = AttemptStatus.CANCELLED
            raise
        finally:
            self._finish_attempt(attempt)

    def _finish_attempt(self, attempt: Attempt) -> None:
        if attempt.status is AttemptStatus.RUNNING:
            verified = self._best is not None and self._best.label is OutcomeLabel.VERIFIED
            attempt.status = AttemptStatus.VERIFIED if verified else AttemptStatus.FAILED
        if self._best is not None:
            attempt.label = self._best.label
            attempt.patch = self._best.patch
        self.bus.publish(
            EventType.ATTEMPT_FINISHED,
            {
                "status": attempt.status.value,
                "label": attempt.label.value if attempt.label else None,
                "changed_lines": attempt.patch.changed_lines if attempt.patch else 0,
            },
            attempt_id=attempt.id,
        )

    def _is_better(self, candidate: Verification) -> bool:
        """Prefer a higher label, then the smaller patch; among failures, the latest one."""
        best = self._best
        if best is None:
            return True
        new_rank, old_rank = label_rank(candidate.label), label_rank(best.label)
        if new_rank != old_rank:
            return new_rank > old_rank
        if new_rank == 0:
            return True
        return candidate.patch.changed_lines < best.patch.changed_lines

    async def _rediagnose(self, verification: Verification, attempt_id: str) -> str:
        run = self._require(self._run)
        reply = await self._gateway.complete(
            ModelRole.PLANNER,
            prompts.rediagnosis_messages(
                run.task, self._plan, verification.describe(), verification.patch.unified_diff
            ),
            attempt_id=attempt_id,
        )
        plan = prompts.parse_plan(reply.content)
        if plan is not None:
            self._plan = plan
            self._publish_plan(plan, "refined", attempt_id=attempt_id)
        return prompts.rediagnosis_feedback(verification.describe(), plan)

    def _new_worker(self, snapshot: Snapshot, phase: ToolPhase) -> Worker:
        context = ToolContext(
            executor=self._executor,
            snapshot=snapshot,
            phase=phase,
            tests=self._tests,
            output_chars=self._limits.tool_output_chars,
            command_timeout_s=self._limits.command_timeout_s,
            web_search=self._web_search,
        )
        worker = Worker(
            self._gateway,
            ToolBox(self._registry, context, self.bus),
            system_prompt=prompts.worker_system_prompt(),
        )
        self._worker = worker
        return worker

    # -- reporting -----------------------------------------------------------------------

    async def _report_with_deadline(self) -> None:
        """Write the report; after a stop, in-flight work is cancelled and 10 s are allowed."""
        try:
            if self._stop_requested:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self._executor.cancel_all(), 5)
                await asyncio.wait_for(self._report(stopped=True), self._stop_deadline_s)
            else:
                await self._report(stopped=False)
        except Exception as exc:
            self._error(
                "report",
                f"The full report could not be built: {type(exc).__name__}: {exc}",
                fatal=True,
            )
            self._write_minimal_report()

    async def _report(self, *, stopped: bool) -> None:
        run = self._require(self._run)
        self._transition(RunStatus.REPORTING)
        stop_reason = self._stop_reason or StopReason.INTERNAL_ERROR
        best = self._best
        label = best.label if best else OutcomeLabel.NOT_VERIFIED
        evidence = best.evidence if best else self._evidence
        snapshot = best.snapshot if best else self._latest_snapshot()
        patch = best.patch if best else await self._partial_patch(snapshot)
        finish = self._best_finish if best else self._last_finish

        summary = finish.summary if finish else ""
        root_cause = finish.root_cause if finish else ""
        citations: list[Citation] = list(finish.citations) if finish else []
        if not stopped and patch is not None and not patch.is_empty:
            evidence_text = best.describe() if best else prompts.baseline_summary(evidence)
            draft = await self._draft_report(patch, evidence_text, finish)
            if draft is not None:
                summary = draft.summary or summary
                root_cause = draft.root_cause_md or root_cause
                citations = list(draft.citations) or citations
        valid, flags = await validate_citations(self._executor, snapshot, citations)
        flags = [*self._platform_flags(), *flags]
        if best is not None and not stopped:
            await self._key_snapshot(best.snapshot, "final-1")

        report = build_report(
            run_id=self.run_id,
            label=label,
            stop_reason=stop_reason,
            summary=summary,
            root_cause_md=root_cause,
            citations=valid,
            patch=patch,
            evidence=evidence,
            flags=flags,
            cost_usd=self._budget.cost_usd,
            tokens=self._budget.snapshot()["tokens"],
            duration_s=self._budget.seconds_elapsed,
            models={**self._settings.models_by_role(), **self._gateway.models_used},
            hypotheses=self._hypothesis_rows,
        )
        self._save_report(run, report)

    async def _draft_report(
        self, patch: Patch, evidence_text: str, finish: FinishArgs | None
    ) -> prompts.ReportDraft | None:
        """Ask the planner for the final explanation; the run's own data is the fallback."""
        run = self._require(self._run)
        try:
            reply = await self._gateway.complete(
                ModelRole.PLANNER,
                prompts.report_messages(run.task, patch.unified_diff, evidence_text, finish),
            )
        except (BudgetExceeded, ModelUnavailableError) as exc:
            self._error("report", f"The report was written without the planner: {exc}")
            return None
        return prompts.parse_report(reply.content)

    def _latest_snapshot(self) -> Snapshot | None:
        if self._worker is not None:
            return self._worker.toolbox.snapshot
        return self._repro or self._installed

    async def _partial_patch(self, snapshot: Snapshot | None) -> Patch | None:
        if snapshot is None or self._installed is None:
            return None
        try:
            return await compute_patch(self._executor, snapshot, timeout_s=GIT_TIMEOUT_S)
        except ExecutorError as exc:
            self._error("report", f"Could not compute the partial patch: {exc}")
            return None

    def _write_minimal_report(self) -> None:
        run = self._require(self._run)
        best = self._best
        report = build_report(
            run_id=self.run_id,
            label=best.label if best else OutcomeLabel.NOT_VERIFIED,
            stop_reason=self._stop_reason or StopReason.INTERNAL_ERROR,
            summary="",
            root_cause_md="",
            citations=[],
            patch=best.patch if best else None,
            evidence=best.evidence if best else self._evidence,
            flags=self._platform_flags(),
            cost_usd=self._budget.cost_usd,
            duration_s=self._budget.seconds_elapsed,
            models=self._settings.models_by_role(),
        )
        self._save_report(run, report)

    def _platform_flags(self) -> list[str]:
        """The 'not the hackathon platform' label (FR-024), when it applies to this run."""
        note = self._settings.platform_note()
        return [note] if note else []

    def _save_report(self, run: Run, report: Report) -> None:
        write_report_files(self.run_dir, report, render_markdown(report, run))
        run.report = report
        run.label = report.label
        run.stop_reason = report.stop_reason
        run.evidence = report.evidence
        if not self._report_published:
            self._report_published = True
            self.bus.publish(EventType.REPORT, report_event(report))

    def _finish_run(self, run: Run) -> None:
        if run.report is None:
            self._write_minimal_report()
        self._transition(RunStatus.DONE)
        run.ended_at = utc_now()
        self.bus.publish(
            EventType.RUN_FINISHED,
            {
                "label": (run.label or OutcomeLabel.NOT_VERIFIED).value,
                "stop_reason": (run.stop_reason or StopReason.INTERNAL_ERROR).value,
                "duration_s": round(self._budget.seconds_elapsed, 3),
                "cost_usd": round(self._budget.cost_usd, 6),
                "patch_available": (self.run_dir / "patch.diff").exists(),
            },
        )

    # -- helpers -------------------------------------------------------------------------

    def _transition(self, status: RunStatus) -> None:
        run = self._require(self._run)
        if run.status is status:
            return
        previous = run.status
        run.status = status
        self.bus.publish(EventType.PHASE_CHANGED, {"from": previous.value, "to": status.value})

    def _publish_plan(self, plan: Plan, stage: str, *, attempt_id: str | None = None) -> None:
        self._require(self._run).plan = list(plan.steps)
        self.bus.publish(
            EventType.PLAN,
            {
                "stage": stage,
                "steps": list(plan.steps),
                "understanding": plan.understanding,
                "suspected_files": list(plan.suspected_files),
            },
            attempt_id=attempt_id,
        )

    async def _key_snapshot(self, snapshot: Snapshot, label: str) -> Snapshot:
        """Tag a key snapshot (a failed tag is reported but not fatal) and record it."""
        try:
            tagged = await self._executor.tag(snapshot, f"fixproof/{self.run_id}/{label}")
        except ExecutorError as exc:
            self._error("sandbox", f"Could not tag the {label} snapshot: {exc}")
            tagged = snapshot
        tagged = tagged.model_copy(update={"label": label})
        self._require(self._run).snapshots.append(tagged)
        self.bus.publish(
            EventType.SNAPSHOT,
            {
                "label": label,
                "image_id": tagged.image_id,
                "tag": tagged.tag,
                "parent_id": tagged.parent_id,
            },
        )
        return tagged

    def _fail(self, reason: StopReason, where: str, message: str) -> None:
        """End the run early with ``reason`` (the first reason wins) and record why."""
        if self._stop_reason is None:
            self._stop_reason = reason
        self._error(where, message, fatal=True)

    def _error(self, where: str, message: str, *, fatal: bool = False) -> None:
        self.bus.publish(EventType.ERROR, {"where": where, "message": message, "fatal": fatal})

    @staticmethod
    def _require(value: _T | None) -> _T:
        if value is None:
            raise RuntimeError("the run is not in the expected state")
        return value


def _tail(result: CommandResult, limit: int) -> str:
    return "\n".join(p for p in (result.stdout, result.stderr) if p).strip()[-limit:]


def _is_test_module(path: str) -> bool:
    name = PurePosixPath(path).name
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))
