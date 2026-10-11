# ADR-0002: Agent Tool Interface and Harness Guards

> **Scope**: Document decision clusters, not individual technology choices. Group related decisions that work together (e.g., "Frontend Stack" not separate ADRs for framework, styling, deployment).

- **Status:** Accepted
- **Date:** 2026-10-11
- **Feature:** 001-verified-fix-agent
- **Context:** The worker model acts only through tools, on untrusted repositories and issue text
  (FR-021). Serving stacks sometimes leak tool-call templates into plain text, and weaker models
  send malformed or out-of-schema arguments. The judges score tool transparency, and the
  constitution requires validated inputs, bounded behavior, and no credentials or network actions
  driven by repository content. Implemented in Phase 3 (`src/fixproof/tools/`,
  `src/fixproof/agent/worker.py`); contract in `contracts/agent-tools.md`.

## Decision

- **One registry, nine tools**: `list_dir`, `read_file`, `search_code`, `create_file`,
  `edit_file`, `run_tests`, `run_command`, `web_search` (only when enabled, FR-022), and `finish`.
  Each has a Pydantic input model (`extra="forbid"`) exported as a self-contained JSON Schema
  (no `$ref`, optional values as `["string", "null"]`), and a phase set (reproduce, fix).
- **Calling protocol**: native tool calls first; a lenient parser accepts `<tool_call>` or fenced
  JSON in the content as a fallback. Results of text-parsed calls go back as user messages, since
  they have no provider call ID. Optional fields sent as `null` take their defaults.
- **Invalid calls never execute**: malformed JSON, unknown tools, tools not offered in the
  current phase, and schema violations return `{"error", "message"}` to the model. Three
  consecutive replies without a valid call (including plain-text replies) end the attempt with
  `invalid_tool_calls`.
- **Guards enforced by the harness, not the prompt**:
  - every path stays inside the repository root; `.git` cannot be written;
  - `run_command` is always disposable and rejects `git push`, `curl`, `wget`, `pip install`,
    `rm -rf /`, and credential variable names;
  - in the reproduce phase, files that existed before the phase are frozen;
  - `edit_file` replaces exactly one occurrence and returns the diff;
  - `finish` requires citations once a fix exists, and never sets the label (ADR-0004).
- **Bounded, traced output**: results to the model are capped at 8,000 characters (longest
  strings cut in the middle with `…[truncated N chars]`, JSON kept valid); `read_file` returns at
  most 400 numbered lines. Every call publishes `tool_call` and exactly one `tool_result`,
  including `stopped` when a run is stopped mid-call. Old tool results collapse to one-line
  summaries when the worker context grows past about 24,000 tokens.

## Consequences

### Positive

- Repository and issue text cannot make the agent push code, reach the network, or read secrets;
  prompt injection is contained by code, not by model obedience.
- Robust to template leaks and malformed arguments; errors teach the model instead of crashing.
- Every action is visible in the trace and checkable by the contract tests (SC-005).
- Tools are plain async functions over the `Executor` protocol, so they are unit-testable offline.

### Negative

- More code than a single shell tool, and the contract must be kept in sync with the registry.
- Exact-match edits can take extra steps when the model copies text imperfectly (mitigated by
  CRLF handling and clear `no_match`/`multiple_matches` errors).
- The forbidden-command list is a denylist; it is defense in depth on top of disposable,
  network-less sandboxes, not a complete policy.
- Strict schemas may cost a few invalid calls with weaker models before they adapt.

## Alternatives Considered

- **One free-form shell tool** (as in mini-swe-agent): simplest, but edits become invisible shell
  side effects, guards are hard to enforce, and the trace cannot show intent. Rejected.
- **JSON-mode-only agent** (the model returns a JSON action without native tools): more brittle
  multi-step state. Rejected (research R3).
- **Grammar-constrained decoding**: not documented on Token Factory. Rejected.
- **Contree MCP server tools**: adds a protocol hop and gives up the harness guards we own.
  Rejected (research R4).

## References

- Feature Spec: [spec.md](../../specs/001-verified-fix-agent/spec.md) (FR-005, FR-010, FR-020,
  FR-021, FR-022)
- Implementation Plan: [plan.md](../../specs/001-verified-fix-agent/plan.md) (D2); research R3;
  [contracts/agent-tools.md](../../specs/001-verified-fix-agent/contracts/agent-tools.md)
- Related ADRs: ADR-0001 (models), ADR-0003 (executors), ADR-0004 (verification)
- Evaluator Evidence: `tests/contract/test_tool_schemas.py`, `tests/unit/test_tool_handlers.py`,
  `tests/unit/test_toolcall.py`; PHR 0020
