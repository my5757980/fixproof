"""Contract test: the tool registry matches the agent-tools contract of feature 001."""

from __future__ import annotations

import json
from typing import Any

import pytest

from fixproof.tools.handlers import ToolPhase
from fixproof.tools.registry import build_registry, web_search_enabled
from fixproof.tools.schemas import ReadFileArgs
from tests.fakes.settings import make_settings

BOTH = {ToolPhase.REPRODUCE, ToolPhase.FIX}

# Transcribed from the contract: description, phases, required fields, and per-field bounds.
CONTRACT: dict[str, dict[str, Any]] = {
    "list_dir": {
        "description": "List files and folders under a repository path, up to a depth.",
        "phases": BOTH,
        "required": set(),
        "properties": {
            "path": {"type": "string", "default": "."},
            "depth": {"type": "integer", "minimum": 1, "maximum": 4, "default": 2},
        },
    },
    "read_file": {
        "description": "Read a range of lines from a repository file, with line numbers.",
        "phases": BOTH,
        "required": {"path"},
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1, "default": 1},
            "end_line": {"type": "integer", "minimum": 1, "default": 200},
        },
    },
    "search_code": {
        "description": (
            "Search repository files for a regular expression and return matching lines."
        ),
        "phases": BOTH,
        "required": {"pattern"},
        "properties": {
            "pattern": {"type": "string", "minLength": 1, "maxLength": 200},
            "path": {"type": "string", "default": "."},
            "glob": {"type": "string", "default": "*.py"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "default": 40},
        },
    },
    "create_file": {
        "description": "Create a new file (fails if it exists), e.g. a reproduction test.",
        "phases": BOTH,
        "required": {"path", "content", "purpose"},
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string", "maxLength": 50000},
            "purpose": {"type": "string", "maxLength": 200},
        },
    },
    "edit_file": {
        "description": "Replace one exact, unique occurrence of text in an existing file.",
        "phases": BOTH,
        "required": {"path", "old_text", "new_text", "purpose"},
        "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string", "minLength": 1, "maxLength": 20000},
            "new_text": {"type": "string", "maxLength": 20000},
            "purpose": {"type": "string", "maxLength": 200},
        },
    },
    "run_tests": {
        "description": (
            "Run pytest on a selector (or the full suite) and return structured results."
        ),
        "phases": BOTH,
        "required": set(),
        "properties": {
            "selector": {"type": ["string", "null"], "maxLength": 500, "default": None},
            "purpose": {"type": "string", "maxLength": 200},
        },
    },
    "run_command": {
        "description": "Run a short, read-only shell command for inspection (e.g. `python -c`).",
        "phases": BOTH,
        "required": {"command", "purpose"},
        "properties": {
            "command": {"type": "string", "maxLength": 1000},
            "timeout_s": {"type": "integer", "minimum": 1, "maximum": 300, "default": 120},
            "purpose": {"type": "string", "maxLength": 200},
        },
    },
    "web_search": {
        "description": (
            "Search the web for documentation or an error message. Send a short query only."
        ),
        "phases": {ToolPhase.FIX},
        "required": {"query"},
        "properties": {"query": {"type": "string", "minLength": 3, "maxLength": 200}},
    },
    "finish": {
        "description": "Declare the attempt done and hand over to independent verification.",
        "phases": BOTH,
        "required": {"summary", "root_cause"},
        "properties": {
            "summary": {"type": "string", "maxLength": 1000},
            "root_cause": {"type": "string", "maxLength": 4000},
            "citations": {"type": "array", "maxItems": 10},
        },
    },
}


def test_registry_has_exactly_the_contract_tools() -> None:
    assert set(build_registry(web_search=True).names()) == set(CONTRACT)
    assert set(build_registry().names()) == set(CONTRACT) - {"web_search"}


@pytest.mark.parametrize("name", sorted(CONTRACT))
def test_tool_schema_matches_contract(name: str) -> None:
    registry = build_registry(web_search=True)
    expected = CONTRACT[name]
    spec = registry.get(name)
    assert spec is not None
    assert spec.description == expected["description"]
    assert spec.description.endswith(".") and "\n" not in spec.description
    assert set(spec.phases) == expected["phases"]

    schema = registry.json_schema(name)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema.get("required", [])) == expected["required"]
    assert set(schema["properties"]) == set(expected["properties"])
    for field, bounds in expected["properties"].items():
        actual = schema["properties"][field]
        for key, value in bounds.items():
            assert actual.get(key) == value, f"{name}.{field}.{key}: {actual.get(key)!r}"


def test_finish_citation_items_match_contract() -> None:
    items = build_registry().json_schema("finish")["properties"]["citations"]["items"]
    assert items["type"] == "object"
    assert set(items["required"]) == {"path", "start_line", "end_line"}
    assert items["properties"]["path"]["type"] == "string"
    assert items["properties"]["start_line"] == {"type": "integer", "minimum": 1}
    assert items["properties"]["end_line"] == {"type": "integer", "minimum": 1}


def test_exported_schemas_are_self_contained() -> None:
    text = json.dumps(build_registry(web_search=True).openai_tools(ToolPhase.FIX))
    assert "$ref" not in text and "$defs" not in text
    assert '"title"' not in text


def test_openai_tools_format_and_phase_availability() -> None:
    registry = build_registry(web_search=True)
    reproduce = registry.openai_tools(ToolPhase.REPRODUCE)
    fix = registry.openai_tools(ToolPhase.FIX)
    assert all(t["type"] == "function" for t in reproduce + fix)
    reproduce_names = {t["function"]["name"] for t in reproduce}
    fix_names = {t["function"]["name"] for t in fix}
    assert "web_search" not in reproduce_names
    assert fix_names == reproduce_names | {"web_search"}
    tool = next(t for t in fix if t["function"]["name"] == "read_file")
    assert tool["function"]["parameters"] == registry.json_schema("read_file")


def test_validate_returns_parsed_args_or_contract_error() -> None:
    registry = build_registry()
    parsed = registry.validate("read_file", {"path": "a.py", "start_line": 3})
    assert isinstance(parsed, ReadFileArgs) and parsed.end_line == 200

    for name, args in [
        ("read_file", {"path": "a.py", "extra": 1}),
        ("read_file", {}),
        ("list_dir", {"depth": 9}),
        ("search_code", {"pattern": ""}),
        ("finish", {"summary": "x", "root_cause": "y", "citations": [{"path": "a.py"}]}),
    ]:
        error = registry.validate(name, args)
        assert isinstance(error, dict), (name, args)
        assert error["error"] == "invalid_arguments"
        assert error["message"]

    unknown = registry.validate("delete_repo", {})
    assert isinstance(unknown, dict) and unknown["error"] == "unknown_tool"


def test_optional_fields_sent_as_null_use_their_defaults() -> None:
    parsed = build_registry().validate("read_file", {"path": "a.py", "start_line": None})
    assert isinstance(parsed, ReadFileArgs) and parsed.start_line == 1


def test_tool_not_offered_in_phase_is_refused() -> None:
    registry = build_registry(web_search=True)
    error = registry.validate("web_search", {"query": "pytest raises"}, ToolPhase.REPRODUCE)
    assert isinstance(error, dict) and error["error"] == "tool_not_available"


def test_web_search_requires_flag_and_key() -> None:
    assert not web_search_enabled(make_settings())
    assert not web_search_enabled(make_settings(web_search=True))
    assert not web_search_enabled(make_settings(tavily_api_key="tvly-123456"))
    assert web_search_enabled(make_settings(web_search=True, tavily_api_key="tvly-123456"))
