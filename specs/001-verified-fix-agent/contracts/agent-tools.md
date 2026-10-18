# Contract: Agent Tools

**Feature**: `001-verified-fix-agent` | **Constitution**: Principle IV (tool transparency), III (validation, bounds)

All tools live in one registry (`src/fixproof/tools/registry.py`). Each tool is:

- defined by a Pydantic input model, which produces the JSON Schema below;
- validated before execution, so invalid arguments are never executed and the validation error is
  returned to the model;
- executed **only inside the sandbox** through the `Executor`;
- logged as a `tool_call` / `tool_result` trace event with a one-line purpose.

Tool output sent back to the model is truncated to `tool_output_chars` (default 8,000), with the
marker `…[truncated N chars]`.

| Tool | Mutates sandbox? | Available in phase | Description (one sentence, shown to the model) |
|------|------------------|--------------------|-----------------------------------------------|
| `list_dir` | no | reproduce, fix | List files and folders under a repository path, up to a depth. |
| `read_file` | no | reproduce, fix | Read a range of lines from a repository file, with line numbers. |
| `search_code` | no | reproduce, fix | Search repository files for a regular expression and return matching lines. |
| `create_file` | **yes** | reproduce, fix | Create a new file (fails if it exists), e.g. a reproduction test. |
| `edit_file` | **yes** | fix (reproduce: new test files only) | Replace one exact, unique occurrence of text in an existing file. |
| `run_tests` | no | reproduce, fix | Run pytest on a selector (or the full suite) and return structured results. |
| `run_command` | no | reproduce, fix | Run a short, read-only shell command for inspection (e.g. `python -c`). |
| `web_search` | no | fix (only when enabled) | Search the web for documentation or an error message. Send a short query only. |
| `finish` | no | reproduce, fix | Declare the attempt done and hand over to independent verification. |

All tool calls refer to paths **relative to the repository root**. Absolute paths and paths that
escape the root via `..` are rejected with `path_outside_repo`.

## Input schemas

```json
{
  "list_dir": {
    "type": "object",
    "properties": {
      "path": { "type": "string", "default": "." },
      "depth": { "type": "integer", "minimum": 1, "maximum": 4, "default": 2 }
    },
    "additionalProperties": false
  },
  "read_file": {
    "type": "object",
    "required": ["path"],
    "properties": {
      "path": { "type": "string" },
      "start_line": { "type": "integer", "minimum": 1, "default": 1 },
      "end_line": { "type": "integer", "minimum": 1, "default": 200 }
    },
    "additionalProperties": false
  },
  "search_code": {
    "type": "object",
    "required": ["pattern"],
    "properties": {
      "pattern": { "type": "string", "minLength": 1, "maxLength": 200 },
      "path": { "type": "string", "default": "." },
      "glob": { "type": "string", "default": "*.py" },
      "max_results": { "type": "integer", "minimum": 1, "maximum": 100, "default": 40 }
    },
    "additionalProperties": false
  },
  "create_file": {
    "type": "object",
    "required": ["path", "content", "purpose"],
    "properties": {
      "path": { "type": "string" },
      "content": { "type": "string", "maxLength": 50000 },
      "purpose": { "type": "string", "maxLength": 200 }
    },
    "additionalProperties": false
  },
  "edit_file": {
    "type": "object",
    "required": ["path", "old_text", "new_text", "purpose"],
    "properties": {
      "path": { "type": "string" },
      "old_text": { "type": "string", "minLength": 1, "maxLength": 20000 },
      "new_text": { "type": "string", "maxLength": 20000 },
      "purpose": { "type": "string", "maxLength": 200 }
    },
    "additionalProperties": false
  },
  "run_tests": {
    "type": "object",
    "properties": {
      "selector": { "type": ["string", "null"], "maxLength": 500, "default": null },
      "purpose": { "type": "string", "maxLength": 200 }
    },
    "additionalProperties": false
  },
  "run_command": {
    "type": "object",
    "required": ["command", "purpose"],
    "properties": {
      "command": { "type": "string", "maxLength": 1000 },
      "timeout_s": { "type": "integer", "minimum": 1, "maximum": 300, "default": 120 },
      "purpose": { "type": "string", "maxLength": 200 }
    },
    "additionalProperties": false
  },
  "web_search": {
    "type": "object",
    "required": ["query"],
    "properties": {
      "query": { "type": "string", "minLength": 3, "maxLength": 200 }
    },
    "additionalProperties": false
  },
  "finish": {
    "type": "object",
    "required": ["summary", "root_cause"],
    "properties": {
      "summary": { "type": "string", "maxLength": 1000 },
      "root_cause": { "type": "string", "maxLength": 4000 },
      "citations": {
        "type": "array",
        "maxItems": 10,
        "items": {
          "type": "object",
          "required": ["path", "start_line", "end_line"],
          "properties": {
            "path": { "type": "string" },
            "start_line": { "type": "integer", "minimum": 1 },
            "end_line": { "type": "integer", "minimum": 1 }
          }
        }
      }
    },
    "additionalProperties": false
  }
}
```

## Outputs (returned to the model as the `tool` message content, JSON)

| Tool | Success output | Error codes |
|------|----------------|-------------|
| `list_dir` | `{"entries": [{"path": str, "type": "file"\|"dir", "size": int}], "truncated": bool}` | `path_outside_repo`, `not_found` |
| `read_file` | `{"path": str, "start_line": int, "end_line": int, "total_lines": int, "text": "<n>: <line>\n..."}` (≤ 400 lines per call) | `path_outside_repo`, `not_found`, `binary_file` |
| `search_code` | `{"matches": [{"path": str, "line": int, "text": str}], "truncated": bool}` | `invalid_pattern` |
| `create_file` | `{"path": str, "created": true, "snapshot": str}` | `already_exists`, `path_outside_repo`, `repro_test_frozen_in_fix` |
| `edit_file` | `{"path": str, "diff": "<unified diff of the edit>", "snapshot": str}` | `not_found`, `no_match`, `multiple_matches` (with count), `test_file_edit_blocked_in_reproduce`, `repro_test_frozen_in_fix` (the reproduction test files during the fix phase), `path_outside_repo` |
| `run_tests` | `{"exit_code": int, "counts": {"passed": n, "failed": n, "error": n, "skipped": n}, "failures": [{"node_id": str, "message": str}], "output_tail": str, "timed_out": bool, "test_run_id": str}` | `timeout` (returned as `timed_out: true`) |
| `run_command` | `{"exit_code": int, "stdout": str, "stderr": str, "timed_out": bool}` | `forbidden_command` (see guards) |
| `web_search` | `{"results": [{"title": str, "url": str, "snippet": str}]}` | `disabled`, `search_failed` |
| `finish` | `{"accepted": true, "next": "verification"}`, after which the harness takes over | `missing_citations` (when a fix exists but there are no citations) |

Errors use the shape `{"error": "<code>", "message": "<what failed and how to fix it>"}`.

## Guards (enforced by the harness, not the model)

- `run_command` runs with `disposable=True`, so it can never change the attempt's snapshot. It
  rejects commands containing `git push`, `curl`, `wget`, `pip install`, or `rm -rf /`, and any
  reference to credential environment variable names. File changes go only through
  `create_file` and `edit_file`, so every change is visible in the trace.
- In the **reproduce** phase, `edit_file` may only touch files the agent created in that phase.
  Existing source files are frozen until the **fix** phase starts.
- Any change to an existing test file during **fix** is allowed but recorded. It caps the label
  at `needs_review` (FR-008).
- `finish` never sets the label. The harness verifies independently (research R8).
- Every tool call increments `steps_used` only when it is part of a model response. Budgets are
  checked before each model call and each sandbox operation.
