"""Extract tool calls from model replies (research.md R3).

Native OpenAI-style ``tool_calls`` are the primary path. Some serving stacks put a JSON tool call
in the message content instead, wrapped in ``<tool_call>...</tool_call>`` or a fenced ``json``
block. This module accepts both, so the agent loop sees one normalized ``ToolCall`` type.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

_TAGGED = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_FENCED = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class ToolCallParseError(ValueError):
    """Raised when a tool call written in message content is not valid JSON.

    Args:
        message: What went wrong.
        snippet: The raw text that could not be parsed.
    """

    def __init__(self, message: str, snippet: str) -> None:
        super().__init__(message)
        self.snippet = snippet


@dataclass(frozen=True)
class ToolCall:
    """A tool call requested by the model.

    Attributes:
        id: Call ID. For native calls this is the provider's ID, which must be echoed back in the
            matching ``tool`` message.
        name: Tool name.
        args: Parsed arguments; empty when ``parse_error`` is set.
        native: Whether the call came from native ``tool_calls`` (``False`` for content fallback).
        parse_error: Why the native arguments could not be parsed, if they could not.
        raw_args: The raw argument string as sent by the model.
    """

    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    native: bool = True
    parse_error: str | None = None
    raw_args: str = ""


def extract_tool_calls(message: Any) -> list[ToolCall]:
    """Return the tool calls in an assistant message.

    Args:
        message: An OpenAI ``ChatCompletionMessage`` or an equivalent ``dict``.

    Returns:
        Native tool calls if present; otherwise calls parsed from the message content; otherwise
        an empty list.

    Raises:
        ToolCallParseError: If a tool call in the message content is malformed JSON.
    """
    data = _as_dict(message)
    native = [_native_call(raw) for raw in data.get("tool_calls") or []]
    if native:
        return native
    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        return []
    return _content_calls(content)


def _as_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return message
    dump = getattr(message, "model_dump", None)
    if callable(dump):
        result = dump()
        if isinstance(result, dict):
            return result
    raise TypeError(f"unsupported message type: {type(message).__name__}")


def _native_call(raw: dict[str, Any]) -> ToolCall:
    function = raw.get("function") or {}
    name = str(function.get("name") or "")
    arguments = function.get("arguments")
    call_id = str(raw.get("id") or _stable_id(name, str(arguments)))
    if isinstance(arguments, dict):
        return ToolCall(id=call_id, name=name, args=arguments, raw_args=json.dumps(arguments))
    raw_args = arguments if isinstance(arguments, str) else ""
    if not raw_args.strip():
        return ToolCall(id=call_id, name=name, args={}, raw_args=raw_args)
    try:
        parsed = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        return ToolCall(
            id=call_id,
            name=name,
            parse_error=f"arguments are not valid JSON: {exc}",
            raw_args=raw_args,
        )
    if not isinstance(parsed, dict):
        return ToolCall(
            id=call_id, name=name, parse_error="arguments must be a JSON object", raw_args=raw_args
        )
    return ToolCall(id=call_id, name=name, args=parsed, raw_args=raw_args)


def _content_calls(content: str) -> list[ToolCall]:
    tagged = _TAGGED.findall(content)
    if tagged:
        return [
            _parse_content_call(snippet, index, strict=True) for index, snippet in enumerate(tagged)
        ]
    calls: list[ToolCall] = []
    for index, snippet in enumerate(_FENCED.findall(content)):
        call = _parse_content_call(snippet, index, strict=False)
        if call is not None:
            calls.append(call)
    return calls


def _parse_content_call(snippet: str, index: int, *, strict: bool) -> Any:
    try:
        obj = json.loads(snippet)
    except json.JSONDecodeError as exc:
        if strict:
            raise ToolCallParseError(f"tool call is not valid JSON: {exc}", snippet) from exc
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("name"), str):
        if strict:
            raise ToolCallParseError("tool call must be a JSON object with a 'name'", snippet)
        return None
    args = obj.get("arguments", obj.get("parameters", obj.get("args", {})))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError as exc:
            raise ToolCallParseError(
                f"tool call arguments are not valid JSON: {exc}", snippet
            ) from exc
    if not isinstance(args, dict):
        raise ToolCallParseError("tool call arguments must be a JSON object", snippet)
    name = obj["name"]
    return ToolCall(
        id=_stable_id(name, snippet, index),
        name=name,
        args=args,
        native=False,
        raw_args=json.dumps(args),
    )


def _stable_id(name: str, payload: str, index: int = 0) -> str:
    digest = hashlib.sha256(f"{index}:{name}:{payload}".encode()).hexdigest()[:12]
    return f"call_fallback_{index}_{digest}"
