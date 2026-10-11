from __future__ import annotations

import pytest

from fixproof.budget import BudgetExceeded, BudgetTracker
from fixproof.models import Budget, StopReason


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make(
    max_steps: int = 10, max_seconds: int = 100, max_cost: float = 1.0
) -> tuple[BudgetTracker, FakeClock]:
    clock = FakeClock()
    budget = Budget(max_steps=max_steps, max_seconds=max_seconds, max_cost_usd=max_cost)
    return BudgetTracker(budget, clock=clock), clock


def test_step_limit() -> None:
    tracker, _ = make(max_steps=5)
    for _ in range(5):
        tracker.check()
        tracker.add_step()
    with pytest.raises(BudgetExceeded) as info:
        tracker.check()
    assert info.value.reason is StopReason.BUDGET_STEPS


def test_check_without_steps_ignores_only_the_step_limit() -> None:
    tracker, clock = make(max_steps=5, max_seconds=60)
    for _ in range(5):
        tracker.add_step()
    tracker.check(steps=False)
    clock.now += 61
    with pytest.raises(BudgetExceeded) as info:
        tracker.check(steps=False)
    assert info.value.reason is StopReason.BUDGET_TIME


def test_time_limit() -> None:
    tracker, clock = make(max_seconds=60)
    tracker.check()
    clock.now += 61
    with pytest.raises(BudgetExceeded) as info:
        tracker.check()
    assert info.value.reason is StopReason.BUDGET_TIME


def test_cost_limit() -> None:
    tracker, _ = make(max_cost=0.5)
    tracker.charge("m", prompt_tokens=10, completion_tokens=5, cost_usd=0.6)
    with pytest.raises(BudgetExceeded) as info:
        tracker.check()
    assert info.value.reason is StopReason.BUDGET_COST


def test_per_model_accounting() -> None:
    tracker, _ = make()
    tracker.charge("ultra", prompt_tokens=100, completion_tokens=10, cost_usd=0.01)
    tracker.charge("ultra", prompt_tokens=50, completion_tokens=5, cost_usd=0.02)
    tracker.charge("super", prompt_tokens=7, completion_tokens=3, cost_usd=0.001)
    usage = tracker.usage
    assert usage["ultra"].prompt_tokens == 150
    assert usage["ultra"].completion_tokens == 15
    assert usage["super"].prompt_tokens == 7
    assert tracker.cost_usd == pytest.approx(0.031)
    snap = tracker.snapshot()
    assert snap["steps_used"] == 0
    assert snap["cost_usd"] == pytest.approx(0.031)
    assert snap["tokens"]["ultra"] == 165


def test_split_divides_remaining_budget_and_propagates() -> None:
    tracker, clock = make(max_steps=20, max_seconds=100, max_cost=1.0)
    tracker.add_step()
    tracker.add_step()
    tracker.charge("m", 1, 1, 0.1)
    clock.now += 10

    children = tracker.split(3)
    assert len(children) == 3
    assert all(child.max_steps == 6 for child in children)  # (20 - 2) // 3
    assert all(child.max_cost_usd == pytest.approx(0.3) for child in children)  # 0.9 / 3

    children[0].add_step()
    children[0].charge("m", 1, 1, 0.05)
    assert tracker.steps_used == 3
    assert tracker.cost_usd == pytest.approx(0.15)

    # Branches share the parent's wall clock: once the parent runs out of time, all stop.
    clock.now += 95
    with pytest.raises(BudgetExceeded) as info:
        children[1].check()
    assert info.value.reason is StopReason.BUDGET_TIME


def test_split_requires_positive_n() -> None:
    tracker, _ = make()
    with pytest.raises(ValueError):
        tracker.split(0)


def test_restart_clock_ignores_time_spent_waiting() -> None:
    tracker, clock = make(max_seconds=60)
    clock.now += 500  # waited in a queue
    tracker.restart_clock()
    tracker.check()
    assert tracker.seconds_elapsed == 0
