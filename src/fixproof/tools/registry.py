"""The tool registry: name → description, input model, handler, and phases (Constitution IV).

The registry is the single source of the tool definitions sent to the model (``tools=``) and of
argument validation. Invalid arguments never reach a handler; the validation error goes back to
the model instead (research R3).
"""

from __future__ import annotations

import typing
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from fixproof.config import Settings
from fixproof.tools import handlers
from fixproof.tools.handlers import ToolContext, ToolInputError, ToolOutcome, ToolPhase
from fixproof.tools.schemas import (
    CreateFileArgs,
    EditFileArgs,
    FinishArgs,
    ListDirArgs,
    ReadFileArgs,
    RunCommandArgs,
    RunTestsArgs,
    SearchCodeArgs,
    ToolArgs,
    WebSearchArgs,
)

Handler = Callable[[ToolContext, Any], Awaitable[ToolOutcome]]

_BOTH = frozenset({ToolPhase.REPRODUCE, ToolPhase.FIX})
_FIX_ONLY = frozenset({ToolPhase.FIX})


@dataclass(frozen=True)
class ToolSpec:
    """One registered tool.

    Attributes:
        name: Tool name shown to the model.
        description: One-sentence description shown to the model.
        args_model: Pydantic model validating the arguments.
        handler: Coroutine executing the tool.
        phases: Phases in which the tool is offered.
        mutates: Whether the tool can change the sandbox snapshot.
    """

    name: str
    description: str
    args_model: type[ToolArgs]
    handler: Handler
    phases: frozenset[ToolPhase]
    mutates: bool = False


class ToolRegistry:
    """Registered tools, their JSON Schemas, and argument validation.

    Args:
        specs: The tools to register.
    """

    def __init__(self, specs: Iterable[ToolSpec]) -> None:
        self._specs = {spec.name: spec for spec in specs}

    def names(self, phase: ToolPhase | None = None) -> list[str]:
        """Return tool names in registration order, optionally only those offered in ``phase``."""
        return [s.name for s in self._specs.values() if phase is None or phase in s.phases]

    def get(self, name: str) -> ToolSpec | None:
        """Return the tool called ``name``, if registered."""
        return self._specs.get(name)

    def json_schema(self, name: str) -> dict[str, Any]:
        """Return the self-contained JSON Schema of a tool's arguments.

        Raises:
            KeyError: If no tool is called ``name``.
        """
        return export_schema(self._specs[name].args_model)

    def openai_tools(self, phase: ToolPhase) -> list[dict[str, Any]]:
        """Return the tool definitions for the OpenAI ``tools=`` parameter in ``phase``."""
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": export_schema(spec.args_model),
                },
            }
            for spec in self._specs.values()
            if phase in spec.phases
        ]

    def parse(
        self, name: str, raw_args: Mapping[str, Any] | None, phase: ToolPhase | None = None
    ) -> ToolArgs:
        """Validate a call and return the parsed arguments.

        Optional fields sent as ``null`` are treated as absent, so their defaults apply.

        Args:
            name: Requested tool.
            raw_args: Arguments from the model.
            phase: Current phase; tools not offered in it are refused.

        Returns:
            The validated arguments.

        Raises:
            ToolInputError: ``unknown_tool``, ``tool_not_available``, or ``invalid_arguments``.
        """
        spec = self._specs.get(name)
        if spec is None:
            available = ", ".join(self.names(phase))
            raise ToolInputError(
                "unknown_tool", f"There is no tool named {name!r}. Available tools: {available}."
            )
        if phase is not None and phase not in spec.phases:
            raise ToolInputError(
                "tool_not_available", f"{name} is not available in the {phase.value} phase."
            )
        args = {
            key: value
            for key, value in dict(raw_args or {}).items()
            if value is not None or _accepts_none(spec.args_model, key)
        }
        try:
            return spec.args_model.model_validate(args)
        except ValidationError as exc:
            raise ToolInputError("invalid_arguments", _describe(exc)) from exc

    def validate(
        self, name: str, raw_args: Mapping[str, Any] | None, phase: ToolPhase | None = None
    ) -> ToolArgs | dict[str, Any]:
        """Return the parsed arguments, or an error result ``{"error": ..., "message": ...}``."""
        try:
            return self.parse(name, raw_args, phase)
        except ToolInputError as exc:
            return exc.output()


def build_registry(*, web_search: bool = False) -> ToolRegistry:
    """Create the registry of the tools in ``contracts/agent-tools.md``.

    Args:
        web_search: Register ``web_search`` (only when enabled and configured, FR-022).

    Returns:
        The registry.
    """
    specs = [
        ToolSpec(
            "list_dir",
            "List files and folders under a repository path, up to a depth.",
            ListDirArgs,
            handlers.list_dir,
            _BOTH,
        ),
        ToolSpec(
            "read_file",
            "Read a range of lines from a repository file, with line numbers.",
            ReadFileArgs,
            handlers.read_file,
            _BOTH,
        ),
        ToolSpec(
            "search_code",
            "Search repository files for a regular expression and return matching lines.",
            SearchCodeArgs,
            handlers.search_code,
            _BOTH,
        ),
        ToolSpec(
            "create_file",
            "Create a new file (fails if it exists), e.g. a reproduction test.",
            CreateFileArgs,
            handlers.create_file,
            _BOTH,
            mutates=True,
        ),
        ToolSpec(
            "edit_file",
            "Replace one exact, unique occurrence of text in an existing file.",
            EditFileArgs,
            handlers.edit_file,
            _BOTH,
            mutates=True,
        ),
        ToolSpec(
            "run_tests",
            "Run pytest on a selector (or the full suite) and return structured results.",
            RunTestsArgs,
            handlers.run_tests,
            _BOTH,
        ),
        ToolSpec(
            "run_command",
            "Run a short, read-only shell command for inspection (e.g. `python -c`).",
            RunCommandArgs,
            handlers.run_command,
            _BOTH,
        ),
    ]
    if web_search:
        specs.append(
            ToolSpec(
                "web_search",
                "Search the web for documentation or an error message. Send a short query only.",
                WebSearchArgs,
                handlers.web_search,
                _FIX_ONLY,
            )
        )
    specs.append(
        ToolSpec(
            "finish",
            "Declare the attempt done and hand over to independent verification.",
            FinishArgs,
            handlers.finish,
            _BOTH,
        )
    )
    return ToolRegistry(specs)


def web_search_enabled(settings: Settings) -> bool:
    """Return whether ``web_search`` is on: ``FIXPROOF_WEB_SEARCH=1`` and a Tavily key."""
    key = settings.tavily_api_key
    return settings.web_search and key is not None and bool(key.get_secret_value())


def export_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return a self-contained JSON Schema for ``model``.

    References are inlined (``$defs`` removed), titles dropped, and optional values written as
    ``"type": ["string", "null"]``, which serving stacks handle more reliably.
    """
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})
    simplified = _simplify(_inline(schema, definitions))
    if not isinstance(simplified, dict):  # pragma: no cover - a model schema is an object
        raise TypeError("expected an object schema")
    return simplified


def _inline(node: Any, definitions: Mapping[str, Any]) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            target = _inline(definitions[ref.removeprefix("#/$defs/")], definitions)
            rest = {k: _inline(v, definitions) for k, v in node.items() if k != "$ref"}
            return {**target, **rest}
        return {key: _inline(value, definitions) for key, value in node.items()}
    if isinstance(node, list):
        return [_inline(item, definitions) for item in node]
    return node


def _simplify(node: Any) -> Any:
    if isinstance(node, list):
        return [_simplify(item) for item in node]
    if not isinstance(node, dict):
        return node
    result: dict[str, Any] = {}
    for key, value in node.items():
        if key == "title":
            continue
        if key == "properties" and isinstance(value, dict):
            result[key] = {name: _simplify(sub) for name, sub in value.items()}
        else:
            result[key] = _simplify(value)
    options = result.get("anyOf")
    null = {"type": "null"}
    if isinstance(options, list) and len(options) == 2 and null in options:
        other = options[0] if options[1] == null else options[1]
        if isinstance(other, dict) and isinstance(other.get("type"), str):
            del result["anyOf"]
            result = {**other, **result, "type": [other["type"], "null"]}
    return result


def _accepts_none(model: type[BaseModel], key: str) -> bool:
    field = model.model_fields.get(key)
    if field is None:
        return True  # unknown keys are kept so ``extra="forbid"`` reports them
    annotation = field.annotation
    return annotation is type(None) or type(None) in typing.get_args(annotation)


def _describe(error: ValidationError) -> str:
    parts = []
    for item in error.errors():
        location = ".".join(str(part) for part in item["loc"]) or "arguments"
        parts.append(f"{location}: {item['msg']}")
    return ("Invalid arguments: " + "; ".join(parts))[:600]
