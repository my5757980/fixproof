"""Scripted fake of the ``ModelClient`` protocol for offline tests (never imported by ``src/``).

Each role has a queue of scripted replies (or exceptions, or callables that build a reply from
the conversation). Every request is recorded so tests can assert on prompts and tools, and on
what the model was (and was not) shown.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import count
from typing import Any

from fixproof.config import DEFAULT_FALLBACK_MODEL, DEFAULT_PLANNER_MODEL, DEFAULT_WORKER_MODEL
from fixproof.llm.client import ModelReply, ModelUnavailableError
from fixproof.llm.toolcall import ToolCall
from fixproof.models import ModelRole

ScriptItem = ModelReply | Exception | Callable[[list[dict[str, Any]]], ModelReply]
_ids = count(1)

ROLE_MODELS = {
    ModelRole.PLANNER: DEFAULT_PLANNER_MODEL,
    ModelRole.WORKER: DEFAULT_WORKER_MODEL,
    ModelRole.CONDENSER: DEFAULT_FALLBACK_MODEL,
}


@dataclass
class RecordedRequest:
    role: ModelRole
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]

    def text(self) -> str:
        """All message contents joined, for 'was X shown to the model?' assertions."""
        return "\n".join(str(m.get("content") or "") for m in self.messages)


class FakeModelClient:
    """Deterministic, scripted model client."""

    def __init__(self, models: Sequence[str] | None = None) -> None:
        self.queues: dict[ModelRole, deque[ScriptItem]] = defaultdict(deque)
        self.requests: list[RecordedRequest] = []
        self.available_models = list(models or ROLE_MODELS.values())

    def script(self, role: ModelRole, *items: ScriptItem) -> FakeModelClient:
        self.queues[role].extend(items)
        return self

    async def complete(
        self,
        role: ModelRole,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> ModelReply:
        conversation = [dict(m) for m in messages]
        self.requests.append(RecordedRequest(role, conversation, [dict(t) for t in tools or []]))
        if not self.queues[role]:
            raise AssertionError(f"FakeModelClient: no scripted reply left for role {role.value}")
        item = self.queues[role].popleft()
        if isinstance(item, Exception):
            raise item
        if callable(item) and not isinstance(item, ModelReply):
            return item(conversation)
        return item

    async def list_models(self) -> list[str]:
        return list(self.available_models)


def _reply(
    content: str | None, calls: list[ToolCall], role: ModelRole, parse_error: str | None = None
) -> ModelReply:
    message: dict[str, Any] = {"role": "assistant", "content": content or ""}
    native = [c for c in calls if c.native]
    if native:
        message["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": c.raw_args or "{}"},
            }
            for c in native
        ]
    return ModelReply(
        content=content,
        tool_calls=calls,
        reasoning=None,
        prompt_tokens=100,
        completion_tokens=20,
        cost_usd=0.0001,
        model=ROLE_MODELS[role],
        message=message,
        parse_error=parse_error,
    )


def reply_tool(
    name: str, *, role: ModelRole = ModelRole.WORKER, content: str | None = None, **args: Any
) -> ModelReply:
    """A reply with one native tool call."""
    call = ToolCall(id=f"call_{next(_ids)}", name=name, args=args, raw_args=json.dumps(args))
    return _reply(content, [call], role)


def reply_tools(
    *calls: tuple[str, dict[str, Any]], role: ModelRole = ModelRole.WORKER
) -> ModelReply:
    """A reply with several native tool calls."""
    tool_calls = [
        ToolCall(id=f"call_{next(_ids)}", name=n, args=a, raw_args=json.dumps(a)) for n, a in calls
    ]
    return _reply(None, tool_calls, role)


def reply_bad_args(name: str, raw_args: str, *, role: ModelRole = ModelRole.WORKER) -> ModelReply:
    """A reply whose native tool call has malformed JSON arguments."""
    call = ToolCall(
        id=f"call_{next(_ids)}",
        name=name,
        parse_error="arguments are not valid JSON",
        raw_args=raw_args,
    )
    return _reply(None, [call], role)


def reply_text(text: str, *, role: ModelRole = ModelRole.WORKER) -> ModelReply:
    """A plain text reply with no tool calls."""
    return _reply(text, [], role)


def reply_json(obj: Any, *, role: ModelRole = ModelRole.PLANNER) -> ModelReply:
    """A text reply whose content is JSON (for planner outputs)."""
    return _reply(json.dumps(obj), [], role)


def unavailable(role: ModelRole = ModelRole.WORKER) -> ModelUnavailableError:
    """An error equivalent to every model in the chain failing (5xx)."""
    return ModelUnavailableError(role, ["fake: InternalServerError"])
