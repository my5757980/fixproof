"""Run budgets: steps, wall-clock time, and cost (FR-006, Constitution III).

A ``BudgetTracker`` is checked before every model call and sandbox operation. Parallel branches
get child trackers whose usage also counts against the parent, so the run as a whole can never
exceed its budget.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fixproof.models import Budget, StopReason


class BudgetExceeded(Exception):
    """Raised when a run or branch hits one of its limits.

    Args:
        reason: Which limit was hit.
        detail: Human-readable description of the limit.
    """

    def __init__(self, reason: StopReason, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


@dataclass
class ModelUsage:
    """Token usage and cost accumulated for one model."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


class BudgetTracker:
    """Track usage against a budget and raise ``BudgetExceeded`` when a limit is reached.

    Args:
        budget: The limits for this run.
        clock: Monotonic clock in seconds; injectable for tests.
        parent: Parent tracker for parallel branches; usage propagates to it.
        max_steps: Override of the step limit (used by ``split``).
        max_cost_usd: Override of the cost limit (used by ``split``).
    """

    def __init__(
        self,
        budget: Budget,
        *,
        clock: Callable[[], float] = time.monotonic,
        parent: BudgetTracker | None = None,
        max_steps: int | None = None,
        max_cost_usd: float | None = None,
    ) -> None:
        self.budget = budget
        self.max_steps = budget.max_steps if max_steps is None else max_steps
        self.max_seconds = budget.max_seconds
        self.max_cost_usd = budget.max_cost_usd if max_cost_usd is None else max_cost_usd
        self._clock = clock
        self._parent = parent
        self._started: float = parent._started if parent is not None else clock()
        self.steps_used = 0
        self.cost_usd = 0.0
        self.usage: dict[str, ModelUsage] = {}

    @property
    def seconds_elapsed(self) -> float:
        """Wall-clock seconds since the run (or the parent run) started."""
        return self._clock() - self._started

    def add_step(self) -> None:
        """Count one model call against the step limit."""
        self.steps_used += 1
        if self._parent is not None:
            self._parent.add_step()

    def charge(
        self, model: str, prompt_tokens: int, completion_tokens: int, cost_usd: float
    ) -> None:
        """Record token usage and cost for ``model``.

        Args:
            model: The model ID that was called.
            prompt_tokens: Input tokens billed.
            completion_tokens: Output tokens billed.
            cost_usd: Cost of the call in USD.
        """
        usage = self.usage.setdefault(model, ModelUsage())
        usage.prompt_tokens += prompt_tokens
        usage.completion_tokens += completion_tokens
        usage.cost_usd += cost_usd
        self.cost_usd += cost_usd
        if self._parent is not None:
            self._parent.charge(model, prompt_tokens, completion_tokens, cost_usd)

    def check(self) -> None:
        """Raise ``BudgetExceeded`` if this tracker or its parent is out of budget.

        Raises:
            BudgetExceeded: With the reason of the first limit that is reached.
        """
        if self._parent is not None:
            self._parent.check()
        if self.steps_used >= self.max_steps:
            raise BudgetExceeded(
                StopReason.BUDGET_STEPS, f"step limit reached ({self.steps_used}/{self.max_steps})"
            )
        if self.seconds_elapsed >= self.max_seconds:
            raise BudgetExceeded(
                StopReason.BUDGET_TIME, f"time limit reached ({self.max_seconds} s)"
            )
        if self.cost_usd >= self.max_cost_usd:
            raise BudgetExceeded(
                StopReason.BUDGET_COST,
                f"cost limit reached (${self.cost_usd:.4f} of ${self.max_cost_usd:.2f})",
            )

    def split(self, n: int) -> list[BudgetTracker]:
        """Divide the remaining steps and cost evenly across ``n`` parallel branches.

        Branches share this tracker's wall clock and report their usage back to it.

        Args:
            n: Number of branches; must be at least 1.

        Returns:
            One child tracker per branch.

        Raises:
            ValueError: If ``n`` is less than 1.
        """
        if n < 1:
            raise ValueError("n must be at least 1")
        steps_each = max(1, (self.max_steps - self.steps_used) // n)
        cost_each = max(0.0, self.max_cost_usd - self.cost_usd) / n
        return [
            BudgetTracker(
                self.budget,
                clock=self._clock,
                parent=self,
                max_steps=steps_each,
                max_cost_usd=cost_each,
            )
            for _ in range(n)
        ]

    def snapshot(self) -> dict[str, Any]:
        """Return the current usage, in the shape of the ``budget`` trace event."""
        return {
            "steps_used": self.steps_used,
            "seconds_elapsed": round(self.seconds_elapsed, 3),
            "cost_usd": round(self.cost_usd, 6),
            "tokens": {
                model: usage.prompt_tokens + usage.completion_tokens
                for model, usage in self.usage.items()
            },
        }
