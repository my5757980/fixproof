"""Scripts for parallel-hypotheses runs on the calc repository.

Concurrent branches share one worker queue, so ``BranchScripts`` routes each worker call to the
script of the hypothesis that its conversation works on.
"""

from __future__ import annotations

from collections import Counter, deque
from typing import Any

from fixproof.llm.client import ModelReply
from tests.fakes.fake_model import reply_json, reply_text, reply_tool
from tests.fakes.scenario import fix_replies, plan_reply, report_reply, reproduce_replies

CORE = ["calc/core.py"]
HYPOTHESES = {
    "hypotheses": [
        {"id": "h1", "statement": "add() subtracts; it should add.", "suspected_files": CORE},
        {"id": "h2", "statement": "add() should keep the sum first.", "suspected_files": CORE},
        {"id": "h3", "statement": "add() should multiply.", "suspected_files": CORE},
    ]
}  # fmt: skip
SLOW = [reply_tool("run_command", command="python -c 'pass'", purpose="inspect")] * 4


def branch_scripts() -> dict[str, list[ModelReply]]:
    """Worker replies per branch: h1 is the smallest fix, h2 a larger and slower one, h3 wrong."""
    return {
        "reproduce": reproduce_replies(),
        "h1": fix_replies(),
        "h2": [*SLOW, *fix_replies(new="result = a + b\n    return result")],
        "h3": fix_replies(new="return a * b"),
    }


def parallel_planner() -> list[ModelReply]:
    """Initial plan, refined plan, hypotheses, and the final report."""
    return [plan_reply(), plan_reply(), reply_json(HYPOTHESES), report_reply()]


class BranchScripts:
    """Route each worker call to the script of the hypothesis its conversation works on."""

    def __init__(self, scripts: dict[str, list[ModelReply]] | None = None) -> None:
        self.queues = {
            name: deque(replies) for name, replies in (scripts or branch_scripts()).items()
        }
        self.calls: Counter[str] = Counter()

    def __call__(self, conversation: list[dict[str, Any]]) -> ModelReply:
        first_user = next(m["content"] for m in conversation if m["role"] == "user")
        name = next(
            (h for h in ("h1", "h2", "h3") if f"Hypothesis {h}:" in first_user), "reproduce"
        )
        self.calls[name] += 1
        if not self.queues[name]:
            return reply_text(f"(no more scripted replies for {name})")
        return self.queues[name].popleft()

    def worker_queue(self, size: int = 80) -> list[Any]:
        """A worker script made of this router, long enough for every branch."""
        return [self] * size
