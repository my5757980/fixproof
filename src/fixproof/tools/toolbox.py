"""Execute tool calls and record each one in the trace (Constitution IV).

Every call publishes a ``tool_call`` event and exactly one matching ``tool_result`` event, even
when the call is invalid, fails, or is interrupted by a stop (``error: "stopped"``).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from fixproof.events import EventBus, EventType
from fixproof.llm.toolcall import ToolCall
from fixproof.models import Snapshot
from fixproof.tools.handlers import (
    ToolContext,
    ToolInputError,
    ToolOutcome,
    fit_output,
    one_line,
    truncate_middle,
)
from fixproof.tools.registry import ToolRegistry

_TRACE_ARG_LIMIT = 20000


@dataclass(frozen=True)
class CallResult:
    """What one tool call produced.

    Attributes:
        call: The call as requested by the model.
        content: JSON text returned to the model (bounded by ``output_chars``).
        outcome: The tool outcome.
        valid: ``False`` when the call itself was malformed (bad JSON, unknown tool, tool not
            offered in this phase, or invalid arguments). Tool errors such as ``not_found``
            are still valid calls.
    """

    call: ToolCall
    content: str
    outcome: ToolOutcome
    valid: bool


class ToolBox:
    """Validate, execute, and trace tool calls for one worker conversation.

    Args:
        registry: The available tools.
        context: Shared tool state (executor, current snapshot, phase).
        bus: The run's event bus.
    """

    def __init__(self, registry: ToolRegistry, context: ToolContext, bus: EventBus) -> None:
        self._registry = registry
        self._context = context
        self._bus = bus

    @property
    def context(self) -> ToolContext:
        """The shared tool state."""
        return self._context

    @property
    def snapshot(self) -> Snapshot:
        """The current snapshot (advanced by ``create_file`` and ``edit_file``)."""
        return self._context.snapshot

    def openai_tools(self) -> list[dict[str, Any]]:
        """Tool definitions offered in the current phase."""
        return self._registry.openai_tools(self._context.phase)

    async def call(self, call: ToolCall) -> CallResult:
        """Validate and execute ``call``, publishing ``tool_call`` and ``tool_result`` events.

        Args:
            call: The tool call requested by the model.

        Returns:
            The result to send back to the model.

        Raises:
            asyncio.CancelledError: When the run is stopped (the result is still recorded).
            Exception: Infrastructure failures (for example a sandbox outage) after they are
                recorded as ``internal_error``.
        """
        started = time.monotonic()
        self._publish_call(call)
        if call.parse_error is not None:
            error = ToolInputError(
                "invalid_arguments",
                f"The arguments are not valid JSON ({call.parse_error}). Send one JSON object "
                "that matches the tool schema.",
            )
            return self._complete(call, ToolOutcome.from_error(error), started, valid=False)
        try:
            args = self._registry.parse(call.name, call.args, self._context.phase)
        except ToolInputError as exc:
            return self._complete(call, ToolOutcome.from_error(exc), started, valid=False)
        spec = self._registry.get(call.name)
        assert spec is not None  # parse() succeeded, so the tool exists
        try:
            outcome = await spec.handler(self._context, args)
        except ToolInputError as exc:
            outcome = ToolOutcome.from_error(exc)
        except asyncio.CancelledError:
            stopped = ToolInputError("stopped", "The run was stopped.")
            self._publish_result(call, ToolOutcome.from_error(stopped), started)
            raise
        except Exception as exc:
            failure = ToolInputError("internal_error", f"{type(exc).__name__}: {exc}")
            self._publish_result(call, ToolOutcome.from_error(failure), started)
            raise
        return self._complete(call, outcome, started, valid=True)

    def skip(self, call: ToolCall, reason: str) -> CallResult:
        """Record ``call`` as not executed (for example after ``finish`` in the same reply)."""
        started = time.monotonic()
        self._publish_call(call)
        outcome = ToolOutcome.from_error(ToolInputError("skipped", reason))
        return self._complete(call, outcome, started, valid=True)

    def _complete(
        self, call: ToolCall, outcome: ToolOutcome, started: float, *, valid: bool
    ) -> CallResult:
        content = fit_output(outcome.output, self._context.output_chars)
        self._publish_result(call, outcome, started)
        return CallResult(call=call, content=content, outcome=outcome, valid=valid)

    def _publish_call(self, call: ToolCall) -> None:
        if call.parse_error is not None:
            args: dict[str, Any] = {"raw": truncate_middle(call.raw_args, _TRACE_ARG_LIMIT)}
        else:
            args = {
                key: truncate_middle(value, _TRACE_ARG_LIMIT) if isinstance(value, str) else value
                for key, value in call.args.items()
            }
        self._bus.publish(
            EventType.TOOL_CALL,
            {"call_id": call.id, "tool": call.name, "args": args, "purpose": _purpose(call)},
            attempt_id=self._context.attempt_id,
        )

    def _publish_result(self, call: ToolCall, outcome: ToolOutcome, started: float) -> None:
        self._bus.publish(
            EventType.TOOL_RESULT,
            {
                "call_id": call.id,
                "tool": call.name,
                "ok": outcome.ok,
                "summary": one_line(outcome.summary),
                "error": outcome.error,
                "elapsed_s": round(time.monotonic() - started, 3),
            },
            attempt_id=self._context.attempt_id,
        )


def _purpose(call: ToolCall) -> str:
    """Return the call's stated purpose, or a short description of what it does."""
    args = call.args
    stated = args.get("purpose")
    if isinstance(stated, str) and stated.strip():
        return one_line(stated)
    described = {
        "list_dir": f"list {args.get('path', '.')}",
        "read_file": (
            f"read {args.get('path', '?')} lines "
            f"{args.get('start_line', 1)}-{args.get('end_line', 200)}"
        ),
        "search_code": f"search for /{args.get('pattern', '')}/",
        "run_tests": f"run tests {args.get('selector') or '(full suite)'}",
        "web_search": f"search the web for {args.get('query', '')!r}",
        "finish": "declare the attempt done",
    }
    return one_line(described.get(call.name, call.name))
