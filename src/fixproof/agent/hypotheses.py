"""Parallel hypotheses (User Story 3, research R9, ADR-0006).

Each hypothesis runs the ordinary worker loop and harness verification in its own sandbox branch
from the ``repro`` snapshot. Branches run concurrently up to ``max_parallel`` and share the run's
budget (``BudgetTracker.split``). When a branch verifies, the others are cancelled unless the run
is exhaustive. The winner is the verified change with the fewest changed lines (FR-014), and every
branch gets a row in the report explaining its outcome.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from fixproof.agent import prompts
from fixproof.agent.prompts import Plan
from fixproof.agent.verify import Verification, label_rank, verify_fix
from fixproof.agent.worker import ModelGateway, Worker, WorkerStatus
from fixproof.budget import BudgetExceeded, BudgetTracker
from fixproof.events import EventBus, EventType
from fixproof.llm.client import ModelClient, ModelUnavailableError
from fixproof.models import (
    Attempt,
    AttemptStatus,
    Budget,
    Evidence,
    Hypothesis,
    HypothesisRow,
    OutcomeLabel,
    Snapshot,
    Task,
)
from fixproof.sandbox.executor import Executor, ExecutorError
from fixproof.sandbox.pytest_results import TestRunner
from fixproof.tools.handlers import ToolContext, ToolPhase, WebSearch
from fixproof.tools.registry import ToolRegistry
from fixproof.tools.schemas import FinishArgs
from fixproof.tools.toolbox import ToolBox


@dataclass(eq=False)
class Branch:
    """One hypothesis and the attempt that tested it."""

    hypothesis: Hypothesis
    attempt: Attempt
    verification: Verification | None = None
    finish: FinishArgs | None = None
    problem: str | None = None
    service_error: Exception | None = None
    models_used: dict[str, str] = field(default_factory=dict)

    @property
    def verified(self) -> bool:
        """Whether the harness verified this branch's fix."""
        return self.verification is not None and self.verification.label is OutcomeLabel.VERIFIED


@dataclass(frozen=True)
class ParallelOutcome:
    """Result of the parallel phase."""

    branches: list[Branch]
    winner: Branch | None
    rows: list[HypothesisRow]

    @property
    def service_error(self) -> Exception | None:
        """A service failure, when no branch reached verification because of one."""
        if any(branch.verification for branch in self.branches):
            return None
        return next((b.service_error for b in self.branches if b.service_error), None)


@dataclass
class BranchSetup:
    """Everything a branch needs that is shared with the rest of the run."""

    model: ModelClient
    sampling: Mapping[str, float | int]
    registry: ToolRegistry
    executor: Executor
    tests: TestRunner
    bus: EventBus
    limits: Budget
    task: Task
    plan: Plan
    paths: Sequence[str]
    repro: Snapshot
    evidence: Evidence
    repro_files: Mapping[str, bytes]
    web_search: WebSearch | None = None


class HypothesisRunner:
    """Run hypotheses concurrently and pick the winner.

    Args:
        setup: Shared run state for the branches.
        budget: The run's budget; branches get equal shares of what is left.
        max_parallel: Branches allowed to run at the same time (1–3).
        exhaustive: Keep running every branch after the first verified one.
    """

    def __init__(
        self, setup: BranchSetup, *, budget: BudgetTracker, max_parallel: int, exhaustive: bool
    ) -> None:
        self._setup = setup
        self._budget = budget
        self._max_parallel = max(1, min(max_parallel, 3))
        self._exhaustive = exhaustive

    async def run(self, hypotheses: Sequence[Hypothesis]) -> ParallelOutcome:
        """Test every hypothesis and return the branches, the winner, and the report rows."""
        repro = self._setup.repro
        branches = [
            Branch(
                hypothesis=hypothesis,
                attempt=Attempt(
                    id=f"a{index}",
                    hypothesis=hypothesis,
                    start_snapshot=repro,
                    current_snapshot=repro,
                ),
            )
            for index, hypothesis in enumerate(hypotheses, start=1)
        ]
        slots = asyncio.Semaphore(self._max_parallel)
        shares = self._budget.split(len(branches))
        tasks = {
            asyncio.create_task(self._run_branch(branch, share, slots)): branch
            for branch, share in zip(branches, shares, strict=True)
        }
        pending = set(tasks)
        try:
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                if not self._exhaustive and any(tasks[task].verified for task in done):
                    await _cancel(pending)
                    pending = set()
        except asyncio.CancelledError:  # the run was stopped: close every branch, then stop
            await _cancel(pending)
            self._close_out(tasks)
            raise
        self._close_out(tasks)
        winner = choose_winner(branches)
        return ParallelOutcome(
            branches=branches, winner=winner, rows=comparison_rows(branches, winner)
        )

    def _close_out(self, tasks: Mapping[asyncio.Task[None], Branch]) -> None:
        """Mark branches that never finished as cancelled and publish every attempt's end."""
        for task, branch in tasks.items():
            if task.cancelled() and branch.attempt.status is AttemptStatus.RUNNING:
                branch.attempt.status = AttemptStatus.CANCELLED
            self._publish_finished(branch)

    async def _run_branch(
        self, branch: Branch, budget: BudgetTracker, slots: asyncio.Semaphore
    ) -> None:
        setup = self._setup
        attempt = branch.attempt
        async with slots:
            gateway = ModelGateway(
                setup.model, budget, setup.bus, setup.sampling, event_budget=self._budget
            )
            context = ToolContext(
                executor=setup.executor,
                snapshot=setup.repro,
                phase=ToolPhase.FIX,
                tests=setup.tests,
                output_chars=setup.limits.tool_output_chars,
                command_timeout_s=setup.limits.command_timeout_s,
                attempt_id=attempt.id,
                web_search=setup.web_search,
            )
            worker = Worker(
                gateway,
                ToolBox(setup.registry, context, setup.bus),
                system_prompt=prompts.worker_system_prompt(),
            )
            message = prompts.hypothesis_fix_message(
                setup.task, setup.plan, setup.evidence, branch.hypothesis, setup.paths
            )
            try:
                result = await worker.run(message)
                attempt.current_snapshot = context.snapshot
                attempt.steps = worker.steps
                if result.status is WorkerStatus.INVALID_TOOL_CALLS:
                    attempt.status = AttemptStatus.FAILED
                    branch.problem = "the model made 3 invalid tool calls in a row"
                    return
                branch.finish = result.finish
                verification = await verify_fix(
                    executor=setup.executor,
                    tests=setup.tests,
                    snapshot=context.snapshot,
                    evidence=setup.evidence,
                    repro_files=setup.repro_files,
                    bus=setup.bus,
                    attempt_id=attempt.id,
                    budget=budget,
                )
                branch.verification = verification
                attempt.patch = verification.patch
                attempt.evidence = verification.evidence
                attempt.label = verification.label
                verified = verification.label is OutcomeLabel.VERIFIED
                attempt.status = AttemptStatus.VERIFIED if verified else AttemptStatus.FAILED
            except BudgetExceeded as exc:
                attempt.status = AttemptStatus.BUDGET_EXHAUSTED
                branch.problem = f"it ran out of its share of the budget ({exc})"
            except (ModelUnavailableError, ExecutorError) as exc:
                attempt.status = AttemptStatus.FAILED
                branch.problem = f"a service was unavailable ({exc})"
                branch.service_error = exc
            finally:
                attempt.steps = worker.steps
                branch.models_used = dict(gateway.models_used)

    def _publish_finished(self, branch: Branch) -> None:
        attempt = branch.attempt
        self._setup.bus.publish(
            EventType.ATTEMPT_FINISHED,
            {
                "status": attempt.status.value,
                "label": attempt.label.value if attempt.label else None,
                "changed_lines": attempt.patch.changed_lines if attempt.patch else 0,
                "hypothesis_id": branch.hypothesis.id,
            },
            attempt_id=attempt.id,
        )


async def _cancel(tasks: set[asyncio.Task[None]]) -> None:
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.wait(tasks)


def choose_winner(branches: Sequence[Branch]) -> Branch | None:
    """Pick the verified branch with the fewest changed lines, else the best other result."""
    verified = [b for b in branches if b.verified and b.verification is not None]
    if verified:
        return min(verified, key=lambda b: (_lines(b), b.attempt.id))
    checked = [b for b in branches if b.verification is not None]
    if not checked:
        return None
    return max(checked, key=lambda b: (label_rank(_label(b)), -_lines(b)))


def comparison_rows(branches: Sequence[Branch], winner: Branch | None) -> list[HypothesisRow]:
    """Explain each branch's outcome for the report's hypothesis table."""
    verified_count = sum(1 for b in branches if b.verified)
    rows = []
    for branch in branches:
        rows.append(
            HypothesisRow(
                hypothesis_id=branch.hypothesis.id,
                statement=branch.hypothesis.statement,
                attempt_status=branch.attempt.status,
                label=branch.attempt.label,
                changed_lines=_lines(branch) if branch.verification else None,
                why=_why(branch, winner, verified_count),
            )
        )
    return rows


def _why(branch: Branch, winner: Branch | None, verified_count: int) -> str:
    if branch is winner and branch.verified:
        if verified_count > 1:
            return f"chosen: verified with the fewest changed lines ({_lines(branch)})"
        return f"chosen: the verified fix ({_lines(branch)} changed lines)"
    if branch.verified and winner is not None:
        return (
            f"also verified, but changed {_lines(branch)} lines; {winner.hypothesis.id} changed "
            f"{_lines(winner)}"
        )
    if branch.attempt.status is AttemptStatus.CANCELLED:
        if winner is not None and winner.verified:
            return f"cancelled when {winner.hypothesis.id} verified first"
        return "cancelled when the run stopped"
    if branch.problem is not None:
        return branch.problem
    verification = branch.verification
    if verification is None:
        return "no result"
    if verification.label is OutcomeLabel.NEEDS_REVIEW:
        return "needs review: existing test files changed, or there were no prior tests"
    passes = verification.repro_passes
    if len(passes) < 3 or not all(passes):
        return f"the reproduction test still fails (passed {sum(passes)} of {len(passes)} runs)"
    if verification.regressions:
        return "regressions: " + ", ".join(verification.regressions[:3])
    return "not verified"


def _lines(branch: Branch) -> int:
    return branch.verification.patch.changed_lines if branch.verification else 0


def _label(branch: Branch) -> OutcomeLabel:
    return branch.verification.label if branch.verification else OutcomeLabel.NOT_VERIFIED
