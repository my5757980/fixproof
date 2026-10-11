# ADR-0007: Unified Event Stream, Trace, and Replay

> **Scope**: Document decision clusters, not individual technology choices. Group related decisions that work together (e.g., "Frontend Stack" not separate ADRs for framework, styling, deployment).

- **Status:** Accepted
- **Date:** 2026-10-11
- **Feature:** 001-verified-fix-agent
- **Context:** Users must watch the plan and every action live in the terminal and on the demo
  page (FR-011); the step record must list every action, command, and test run in order, and a
  report may not claim anything absent from it (FR-010, SC-005). Credentials must never appear in
  records (FR-020). When the demo's limits or funding run out, judges must see a clearly labeled
  replay of a real run (FR-018). Implemented in Phase 2 and 3 for the CLI and trace
  (`src/fixproof/events.py`, `src/fixproof/trace.py`, `src/fixproof/cli.py`); the web stream is
  planned for Phase 4.

## Decision

- **One `EventBus` per run** carrying the 20 event types of `contracts/trace-events.md`, with a
  strictly increasing `seq`, timestamps, and an optional `attempt_id`.
- **Redaction at the source**: every event's data passes through a redactor (configured secret
  values plus `api_key`/`token`/`secret` assignments) before it is stored or published; the trace
  writer redacts again.
- **One stream, many consumers**: the JSONL trace writer (`runs/<run_id>/trace.jsonl`), the CLI
  renderer (one line per event; plans in full), and, in the web demo, Server-Sent Events built on
  Starlette's `StreamingResponse`. Subscribers receive the history first, then live events.
- **Guarantees, enforced by contract tests**: every `tool_call` has exactly one `tool_result`;
  `run_finished` is always last; the report's patch files and test runs all have matching events;
  `run_started` and every `model_call` carry the sampling parameters.
- **Replay = recorded real runs only**: `fixproof replay` and the demo re-emit a stored trace in
  `seq` order with `replay: true`, and every replayed line or page is labeled REPLAY.

## Consequences

### Positive

- What users see, what is recorded, and what is replayed cannot diverge.
- Secrets are removed before anything leaves the process.
- The trace is the evidence for every report claim and doubles as the demo's fallback content.
- Easy to test: the contract tests read the same JSONL the users get.

### Negative

- The bus is in-process: one run lives in one server process, which caps horizontal scaling (fine
  for hackathon traffic).
- Traces can grow large (tool arguments up to 20,000 characters each).
- Any new event or field requires a contract update and test changes.
- Replays show real but old runs; they must never be mistaken for live work, which the labeling
  rule guards.

## Alternatives Considered

- **Separate logging plus WebSockets**: two records that can drift, and bidirectional sockets we
  do not need. Rejected.
- **OpenTelemetry tracing backend**: strong tooling but an external service and a poor fit for a
  user-facing step record. Rejected.
- **A database-backed event store**: unnecessary for local-files-only storage. Rejected.
- **`sse-starlette` or a React frontend**: an extra dependency or a second ecosystem for no real
  gain. Rejected (research R10).

## References

- Feature Spec: [spec.md](../../specs/001-verified-fix-agent/spec.md) (FR-010, FR-011, FR-018,
  FR-020, SC-005)
- Implementation Plan: [plan.md](../../specs/001-verified-fix-agent/plan.md) (D7); research R10;
  [contracts/trace-events.md](../../specs/001-verified-fix-agent/contracts/trace-events.md)
- Related ADRs: ADR-0005 (lifecycle events), ADR-0008 (demo streaming and replay)
- Evaluator Evidence: `tests/contract/test_trace_contract.py`, `tests/unit/test_events_trace.py`,
  `tests/integration/test_cli.py` (replay); PHR 0019 and 0020
