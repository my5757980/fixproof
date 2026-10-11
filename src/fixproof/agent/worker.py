"""The bounded worker tool loop, and the gateway every model call goes through.

``ModelGateway`` checks the budget before each model call, charges its cost, and publishes the
``model_call`` event (with the sampling parameters, Constitution IV). ``Worker`` holds one
conversation: it sends the tools of the current phase, executes the requested calls through the
``ToolBox``, and stops on ``finish``, after 3 consecutive invalid calls, or at a turn limit.
Budget limits, an unavailable model, and cancellation propagate as exceptions to the
orchestrator.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from fixproof.agent import prompts
from fixproof.budget import BudgetTracker
from fixproof.events import EventBus, EventType
from fixproof.llm.client import ModelClient, ModelReply
from fixproof.models import ModelRole, Snapshot
from fixproof.tools.schemas import FinishArgs
from fixproof.tools.toolbox import CallResult, ToolBox

REASONING_LIMIT = 4000
BUDGET_EVENT_EVERY = 5
_COLLAPSED = "[older tool result collapsed] "


class ModelGateway:
    """Every model call of a run: budget check, cost accounting, and trace events.

    Args:
        model: The model client (Token Factory, or a fake in tests).
        budget: The budget tracker the calls are charged to (a branch's share in parallel mode).
        bus: The run's event bus.
        sampling: The sampling parameters sent with every call, recorded in each event.
        event_budget: The tracker shown in ``budget`` events; defaults to ``budget``. Parallel
            branches pass the run's tracker so users see run totals.
    """

    def __init__(
        self,
        model: ModelClient,
        budget: BudgetTracker,
        bus: EventBus,
        sampling: Mapping[str, float | int],
        *,
        event_budget: BudgetTracker | None = None,
    ) -> None:
        self._model = model
        self._budget = budget
        self._event_budget = event_budget or budget
        self._bus = bus
        self._sampling = dict(sampling)
        self.models_used: dict[str, str] = {}

    @property
    def budget(self) -> BudgetTracker:
        """The budget every call is charged to."""
        return self._budget

    @property
    def bus(self) -> EventBus:
        """The event bus the calls are recorded on."""
        return self._bus

    async def complete(
        self,
        role: ModelRole,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
        *,
        attempt_id: str | None = None,
    ) -> ModelReply:
        """Check the budget, call the model, and record the call.

        Raises:
            BudgetExceeded: If a limit was reached before the call.
            ModelUnavailableError: If every model in the role's chain failed.
        """
        self._budget.check()
        reply = await self._model.complete(role, messages, tools)
        self._budget.add_step()
        self._budget.charge(
            reply.model, reply.prompt_tokens, reply.completion_tokens, reply.cost_usd
        )
        self.models_used[role.value] = reply.model
        self._bus.publish(
            EventType.MODEL_CALL,
            {
                "role": role.value,
                "model": reply.model,
                "temperature": self._sampling.get("temperature"),
                "max_tokens": self._sampling.get("max_tokens"),
                "top_p": self._sampling.get("top_p"),
                "prompt_tokens": reply.prompt_tokens,
                "completion_tokens": reply.completion_tokens,
                "cost_usd": round(reply.cost_usd, 8),
                "elapsed_s": round(reply.elapsed_s, 3),
                "fallback_from": reply.fallback_from,
                "has_reasoning": bool(reply.reasoning),
            },
            attempt_id=attempt_id,
        )
        if reply.fallback_from:
            self._bus.publish(
                EventType.ERROR,
                {
                    "where": "model_call",
                    "message": f"{reply.fallback_from} was unavailable; {reply.model} answered.",
                    "fatal": False,
                },
                attempt_id=attempt_id,
            )
        if reply.reasoning:
            self._bus.publish(
                EventType.REASONING,
                {"role": role.value, "text": reply.reasoning[:REASONING_LIMIT]},
                attempt_id=attempt_id,
            )
        if self._event_budget.steps_used % BUDGET_EVENT_EVERY == 0:
            snapshot = self._event_budget.snapshot()
            self._bus.publish(EventType.BUDGET, {**snapshot, "limit_hit": None})
        return reply


class WorkerStatus(StrEnum):
    """Why a worker turn loop ended."""

    FINISHED = "finished"
    INVALID_TOOL_CALLS = "invalid_tool_calls"
    MAX_TURNS = "max_turns"


@dataclass(frozen=True)
class WorkerResult:
    """Result of one ``Worker.run`` call.

    Attributes:
        status: Why the loop ended.
        finish: The accepted ``finish`` payload, when ``status`` is ``finished``.
        snapshot: The latest snapshot of the conversation.
        turns: Model calls made in this ``run`` call.
    """

    status: WorkerStatus
    finish: FinishArgs | None
    snapshot: Snapshot
    turns: int


class Worker:
    """One worker conversation over a ``ToolBox``.

    Args:
        gateway: The model gateway (budget and trace).
        toolbox: Executes tool calls for this conversation.
        system_prompt: The worker system prompt.
        max_invalid: Consecutive invalid replies that end the loop.
        context_tokens: Estimated prompt size above which old tool results are collapsed.
        keep_recent: Number of most recent tool results never collapsed.
    """

    def __init__(
        self,
        gateway: ModelGateway,
        toolbox: ToolBox,
        *,
        system_prompt: str,
        max_invalid: int = 3,
        context_tokens: int = 24000,
        keep_recent: int = 6,
    ) -> None:
        self._gateway = gateway
        self._toolbox = toolbox
        self._max_invalid = max_invalid
        self._context_tokens = context_tokens
        self._keep_recent = keep_recent
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        self.steps = 0
        self._summaries: dict[int, str] = {}
        self._collapsed: set[int] = set()

    @property
    def toolbox(self) -> ToolBox:
        """The tool box of this conversation."""
        return self._toolbox

    @property
    def attempt_id(self) -> str | None:
        """The attempt the conversation's events belong to."""
        return self._toolbox.context.attempt_id

    @attempt_id.setter
    def attempt_id(self, value: str | None) -> None:
        self._toolbox.context.attempt_id = value

    async def run(self, user_message: str, *, max_turns: int | None = None) -> WorkerResult:
        """Send ``user_message`` and loop over tool calls until ``finish`` or a limit.

        Args:
            user_message: The instruction for this part of the conversation.
            max_turns: Maximum model calls in this call, or ``None`` for budget-only limits.

        Returns:
            Why the loop ended, with the ``finish`` payload when there is one.

        Raises:
            BudgetExceeded: When the run budget is exhausted before a model call.
            ModelUnavailableError: When no worker model is available.
        """
        self.messages.append({"role": "user", "content": user_message})
        turns = 0
        invalid_streak = 0
        while max_turns is None or turns < max_turns:
            self._trim_context()
            reply = await self._gateway.complete(
                ModelRole.WORKER,
                self.messages,
                self._toolbox.openai_tools(),
                attempt_id=self.attempt_id,
            )
            turns += 1
            self.steps += 1
            self.messages.append(reply.message or {"role": "assistant", "content": reply.content})
            if not reply.tool_calls:
                invalid_streak += 1
                self._no_tool_call(reply)
                if invalid_streak >= self._max_invalid:
                    return self._result(WorkerStatus.INVALID_TOOL_CALLS, None, turns)
                continue
            finish: FinishArgs | None = None
            any_valid = False
            for call in reply.tool_calls:
                if finish is not None:
                    result = self._toolbox.skip(call, "finish was already called in this step")
                else:
                    result = await self._toolbox.call(call)
                    finish = result.outcome.finish
                any_valid = any_valid or result.valid
                self._append_tool_result(result)
            if finish is not None:
                return self._result(WorkerStatus.FINISHED, finish, turns)
            invalid_streak = 0 if any_valid else invalid_streak + 1
            if invalid_streak >= self._max_invalid:
                return self._result(WorkerStatus.INVALID_TOOL_CALLS, None, turns)
        return self._result(WorkerStatus.MAX_TURNS, None, turns)

    def _result(self, status: WorkerStatus, finish: FinishArgs | None, turns: int) -> WorkerResult:
        return WorkerResult(status, finish, self._toolbox.snapshot, turns)

    def _no_tool_call(self, reply: ModelReply) -> None:
        detail = f" ({reply.parse_error})" if reply.parse_error else ""
        self._gateway.bus.publish(
            EventType.ERROR,
            {
                "where": "worker",
                "message": f"the model replied without a valid tool call{detail}",
                "fatal": False,
            },
            attempt_id=self.attempt_id,
        )
        self.messages.append(
            {"role": "user", "content": prompts.no_tool_call_feedback(reply.parse_error)}
        )

    def _append_tool_result(self, result: CallResult) -> None:
        if result.call.native:
            message = {"role": "tool", "tool_call_id": result.call.id, "content": result.content}
        else:
            # Calls parsed from text have no provider call ID; return the result as user text.
            message = {
                "role": "user",
                "content": f"Result of {result.call.name} (call {result.call.id}):\n"
                f"{result.content}",
            }
        self.messages.append(message)
        self._summaries[len(self.messages) - 1] = result.outcome.summary

    def _estimated_tokens(self) -> int:
        chars = 0
        for message in self.messages:
            chars += len(str(message.get("content") or ""))
            if "tool_calls" in message:
                chars += len(json.dumps(message["tool_calls"]))
        return chars // 4

    def _trim_context(self) -> None:
        """Collapse older tool results to one-line summaries when the prompt grows too large."""
        if self._estimated_tokens() <= self._context_tokens:
            return
        indexes = sorted(self._summaries)
        for index in indexes[: max(len(indexes) - self._keep_recent, 0)]:
            if index in self._collapsed:
                continue
            message = dict(self.messages[index])
            message["content"] = _COLLAPSED + self._summaries[index]
            self.messages[index] = message
            self._collapsed.add(index)
            if self._estimated_tokens() <= self._context_tokens:
                return
