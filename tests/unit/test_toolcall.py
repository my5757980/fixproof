from __future__ import annotations

import pytest
from openai.types.chat import ChatCompletionMessage

from fixproof.llm.toolcall import ToolCallParseError, extract_tool_calls


def native_message(
    *calls: tuple[str, str, str], content: str | None = None
) -> ChatCompletionMessage:
    return ChatCompletionMessage.model_validate(
        {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {"id": cid, "type": "function", "function": {"name": name, "arguments": args}}
                for cid, name, args in calls
            ],
        }
    )


def test_native_tool_calls() -> None:
    msg = native_message(
        ("call_1", "read_file", '{"path": "src/a.py", "start_line": 1}'),
        ("call_2", "run_tests", '{"selector": null}'),
    )
    calls = extract_tool_calls(msg)
    assert [c.name for c in calls] == ["read_file", "run_tests"]
    assert calls[0].id == "call_1"
    assert calls[0].args == {"path": "src/a.py", "start_line": 1}
    assert calls[0].native is True
    assert calls[0].parse_error is None


def test_native_call_with_malformed_arguments_keeps_id() -> None:
    msg = native_message(("call_9", "edit_file", '{"path": "a.py", "old_text": '))
    [call] = extract_tool_calls(msg)
    assert call.id == "call_9"
    assert call.parse_error is not None
    assert call.args == {}


def test_tagged_tool_call_in_content() -> None:
    content = (
        "I will look at the file.\n"
        '<tool_call>{"name": "read_file", "arguments": {"path": "x.py"}}</tool_call>'
    )
    [call] = extract_tool_calls({"role": "assistant", "content": content})
    assert call.name == "read_file"
    assert call.args == {"path": "x.py"}
    assert call.native is False


def test_fenced_json_tool_call() -> None:
    call_json = '{"name": "run_tests", "arguments": {"selector": "tests/test_a.py"}}'
    content = f"Next step:\n```json\n{call_json}\n```"
    [call] = extract_tool_calls({"role": "assistant", "content": content})
    assert call.name == "run_tests"
    assert call.args == {"selector": "tests/test_a.py"}


def test_multiple_tagged_calls() -> None:
    content = (
        '<tool_call>{"name": "list_dir", "arguments": {}}</tool_call>'
        '<tool_call>{"name": "read_file", "parameters": {"path": "b.py"}}</tool_call>'
    )
    calls = extract_tool_calls({"role": "assistant", "content": content})
    assert [c.name for c in calls] == ["list_dir", "read_file"]
    assert calls[1].args == {"path": "b.py"}
    assert calls[0].id != calls[1].id


def test_malformed_tagged_call_raises_with_snippet() -> None:
    content = '<tool_call>{"name": "read_file", "arguments": {"path": </tool_call>'
    with pytest.raises(ToolCallParseError) as info:
        extract_tool_calls({"role": "assistant", "content": content})
    assert '"name": "read_file"' in info.value.snippet


def test_plain_text_has_no_calls() -> None:
    assert extract_tool_calls({"role": "assistant", "content": "The fix is ready."}) == []
    assert extract_tool_calls({"role": "assistant", "content": None}) == []


def test_fenced_json_without_name_is_not_a_call() -> None:
    content = '```json\n{"understanding": "x", "steps": ["a"]}\n```'
    assert extract_tool_calls({"role": "assistant", "content": content}) == []
